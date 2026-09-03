#!/usr/bin/env python3
"""
Wine / Proton Compatibility Patcher for OK-WuWa (ok-wuthering-waves).

Patching model (quilt-style, idempotent by construction):
- Pristine content is sourced from the upstream release zip, cached under
  ~/.cache/ok-wuwa/pristine/<version>/, so re-patching never stacks edits
  and survives ok-ww self-updates.
- Every apply pass rebuilds each target from pristine + transforms, then
  validates AST before an atomic replace.
- If the upstream cache is unavailable (offline), the .orig backup taken
  at first patch time is used as a pristine stand-in.
- --revert restores pristine from the cache (or .orig fallback).
- --status / --verify report patch presence and AST integrity.
- Trees with multiple hardlinked user dirs are each patched independently.
"""

import argparse
import ast
import io
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from typing import Callable, Dict, List, Optional, Tuple

CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".cache", "ok-wuwa", "pristine")
APP_REPO = "ok-oldking/ok-ww-update"
PYPI_PKGS = {
    "qframelesswindow": "PySideSix-Frameless-Window",
    "qfluentwidgets": "PySide6-Fluent-Widgets",
}
FILE_TIMEOUT = 30

WINE_FUNC = (
    "def is_wine():\n"
    "    try:\n"
    "        import ctypes\n"
    "        return hasattr(ctypes.cdll.ntdll, 'wine_get_version')\n"
    "    except Exception:\n"
    "        return False\n\n"
)


def _http_get(url: str, timeout: int = FILE_TIMEOUT) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "ok-wuwa-patcher"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def detect_version(working_dir: str) -> Optional[str]:
    try:
        cfg = open(os.path.join(working_dir, "config.py"), encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    m = re.search(r'^version\s*=\s*"(v[\d.]+)"', cfg, re.M)
    if not m:
        app_json = os.path.join(os.path.dirname(working_dir), "..", "..", "..", "app.json")
        try:
            with open(os.path.normpath(app_json), encoding="utf-8") as f:
                return json.load(f).get("current_version")
        except Exception:
            return None
    return m.group(1)


def _pkg_version(site_packages: str, import_name: str) -> Optional[str]:
    for entry in os.listdir(site_packages):
        if entry.endswith(".dist-info"):
            d = os.path.join(site_packages, entry)
            try:
                rec = open(os.path.join(d, "RECORD"), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if any(f"{import_name}/" in line for line in rec.splitlines()):
                m = re.match(r"([A-Za-z0-9_.-]+)-(\d[\w.*!+-]*)\.dist-info", entry)
                if m:
                    return m.group(2)
    return None


class PristineSource:
    """Pristine content per target file:
    - app modules -> raw.githubusercontent ok-ww-update at the version tag
    - GUI packages -> the PyPI wheel recorded in the installed dist-info
    Everything is cached on disk so re-runs are offline-friendly, and a
    .orig snapshot is kept as a last-resort fallback.
    """

    def __init__(self, version: Optional[str], site_packages: Optional[str]):
        self.version = version
        self.cache_dir = os.path.join(CACHE_ROOT, version or "unknown")
        self.site_packages = site_packages
        self.app_net_ok = True
        self.pypi_net_ok = True

    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, key.replace("/", os.sep) + ".pristine")

    def _load_cache(self, key: str) -> Optional[str]:
        p = self._cache_path(key)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace", newline="") as f:
                return f.read()
        return None

    def _store_cache(self, key: str, content: str):
        p = self._cache_path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(content)

    def _fetch_app(self, rel: str) -> Optional[str]:
        if not self.version or not self.app_net_ok:
            return None
        try:
            raw = _http_get(f"https://raw.githubusercontent.com/{APP_REPO}/{self.version}/{rel}")
            return raw.decode("utf-8", "replace") if raw is not None else None
        except Exception:
            self.app_net_ok = False
            print(f"  [WARN] Upstream fetch failed for {rel}; falling back to local .orig backups.")
            return None

    def _fetch_pypi(self, rel: str) -> Optional[str]:
        if not self.site_packages or not self.pypi_net_ok:
            return None
        top = rel.split("/", 1)[0]
        pypi_name = PYPI_PKGS.get(top)
        if not pypi_name:
            return None
        version = _pkg_version(self.site_packages, top)
        if not version:
            return None
        try:
            meta_raw = _http_get(f"https://pypi.org/pypi/{pypi_name}/{version}/json")
            if meta_raw is None:
                raise OSError(f"no metadata for {pypi_name}=={version}")
            meta = json.loads(meta_raw.decode())
            wheel = next(u for u in meta["urls"] if u["filename"].endswith(".whl"))
            data = _http_get(wheel["url"], timeout=120)
            if data is None:
                raise OSError(f"no wheel for {pypi_name}=={version}")
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                member = next(n for n in z.namelist() if n == rel or n.endswith("/" + rel))
                return z.read(member).decode("utf-8", "replace")
        except Exception:
            self.pypi_net_ok = False
            print(f"  [WARN] PyPI fetch failed for {rel}; falling back to local .orig backups.")
            return None

    def get(self, file_path: str, rel: str) -> Optional[str]:
        cached = self._load_cache(rel)
        if cached is not None:
            return cached
        top = rel.split("/", 1)[0]
        if top in PYPI_PKGS:
            content = self._fetch_pypi(rel)
        else:
            content = self._fetch_app(rel)
        if content is not None:
            self._store_cache(rel, content)
            return content
        orig = file_path + ".orig"
        if os.path.isfile(orig):
            with open(orig, encoding="utf-8", errors="replace", newline="") as f:
                return f.read()
        return None


# ------------------------- engine -------------------------

class PatchEngine:
    def __init__(self, prefix_path: str, offline: bool = False):
        self.prefix_path = os.path.abspath(prefix_path)
        self.offline = offline
        self.trees: List[Tuple[Optional[str], Optional[str]]] = self._locate_directories()

    def _locate_directories(self) -> List[Tuple[Optional[str], Optional[str]]]:
        users_dir = os.path.join(self.prefix_path, "drive_c", "users")
        trees = []
        if not os.path.isdir(users_dir):
            return trees
        for user_entry in sorted(os.listdir(users_dir)):
            app_dir = os.path.join(users_dir, user_entry, "AppData", "Local", "ok-ww", "data", "apps", "ok-ww")
            sp = os.path.join(app_dir, "python", "Lib", "site-packages")
            wk = os.path.join(app_dir, "working")
            site_packages = sp if os.path.isdir(sp) else None
            working_dir = wk if os.path.isdir(wk) and os.path.isfile(os.path.join(wk, "main.py")) else None
            if site_packages or working_dir:
                trees.append((site_packages, working_dir))
        return trees

    @property
    def working_dir(self) -> Optional[str]:
        return self.trees[0][1] if self.trees else None

    @staticmethod
    def _safe_write(file_path: str, content: str) -> bool:
        if file_path.endswith(".py"):
            try:
                ast.parse(content, filename=file_path)
            except SyntaxError as e:
                print(f"  [ERROR] AST validation failed for {file_path}: {e}")
                return False
        d = os.path.dirname(file_path)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".okww-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(content.encode("utf-8"))
            # keep hardlink trees independent: replace, never in-place write
            os.replace(tmp, file_path)
            return True
        except Exception as e:
            print(f"  [ERROR] Write failed for {file_path}: {e}")
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return False

    @staticmethod
    def _eol_of(content: str) -> str:
        if "\r\n" in content:
            return "\r\n"
        return "\n"

    @classmethod
    def _with_native_eol(cls, transform: Callable[[str], Tuple[str, List[str]]], content: str) -> Tuple[str, List[str]]:
        """Run a transform written for LF text on content with any EOL,
        then restore the original EOL style byte-for-byte."""
        eol = cls._eol_of(content)
        normalized = content.replace("\r\n", "\n")
        patched, missing = transform(normalized)
        if eol == "\r\n":
            # the transform inserts fresh \n in its replacement text
            patched = patched.replace("\n", "\r\n")
            # guard against any pre-existing \r\r\n artifacts
            patched = patched.replace("\r\r\n", "\r\n")
        return patched, missing

    @staticmethod
    def _sub(content: str, old: str, new: str, label: str) -> Tuple[str, List[str]]:
        if old not in content:
            return content, [label]
        return content.replace(old, new), []

    @staticmethod
    def _transform(content: str, subs: List[Tuple[str, str, str]]) -> Tuple[str, List[str]]:
        missing = []
        for old, new, label in subs:
            if old not in content:
                missing.append(label)
            content = content.replace(old, new)
        return content, missing

    def _patch_file(self, file_path: str, rel: str, pristine: Optional[str],
                    transforms: Callable[[str], Tuple[str, List[str]]],
                    label: str) -> None:
        if pristine is None:
            print(f"  [WARN] No pristine source for {rel}; skipping {label}")
            return
        self._ensure_backup(file_path, pristine)
        content, missing = self._with_native_eol(transforms, pristine)
        for m in missing:
            print(f"  [WARN] Patch site missing in {rel}: {m} (upstream changed?)")
        if self._safe_write(file_path, content):
            print(f"  -> Patched {rel}")

    def _ensure_backup(self, file_path: str, pristine: str):
        orig = file_path + ".orig"
        with open(orig, "w", encoding="utf-8", newline="") as f:
            f.write(pristine)

    # ------------------ commands ------------------

    def apply_patches(self) -> bool:
        print(f"[*] Target Wine Prefix: {self.prefix_path}")
        if not self.trees:
            print("[WARN] No OK-WW installation found in prefix.")
            return True
        ok = True
        for i, (site_packages, working_dir) in enumerate(self.trees, 1):
            if len(self.trees) > 1:
                print(f"[*] Install tree {i}/{len(self.trees)}")
            version = detect_version(working_dir) if working_dir else None
            source = PristineSource(version, site_packages)
            if site_packages:
                print(f"[1/2] Patching GUI framework packages in {site_packages}...")
                self._patch_gui_packages(site_packages, source)
            if working_dir:
                print(f"[2/2] Patching application modules in {working_dir}...")
                self._patch_app_modules(working_dir, source)
        print("[*] Verifying patched files...")
        return self.verify() and ok

    def revert_patches(self) -> bool:
        print(f"[*] Reverting patches in: {self.prefix_path}")
        restored = 0
        for site_packages, working_dir in self.trees:
            version = detect_version(working_dir) if working_dir else None
            source = PristineSource(version, site_packages)
            if site_packages:
                for rel, _ in PATCHES_GUI:
                    fp = os.path.join(site_packages, rel)
                    restored += self._revert_one(fp, rel, source)
            if working_dir:
                for rel, _ in PATCHES_APP:
                    fp = os.path.join(working_dir, rel)
                    restored += self._revert_one(fp, rel, source)
        print(f"[*] Restored {restored} file(s) to pristine condition.")
        return True

    def _revert_one(self, fp: str, rel: str, source: PristineSource) -> int:
        pristine = source.get(fp, rel)
        if pristine is None:
            if not os.path.isfile(fp):
                return 0
            print(f"  [WARN] No pristine for {rel}; leaving as-is")
            return 0
        if self._safe_write(fp, pristine):
            try:
                os.unlink(fp + ".orig")
            except OSError:
                pass
            return 1
        return 0

    def verify(self) -> bool:
        errors = 0
        checked = 0
        for site_packages, working_dir in self.trees:
            if site_packages:
                for rel, _ in PATCHES_GUI:
                    p = os.path.join(site_packages, rel)
                    if os.path.isfile(p):
                        checked += 1
                        try:
                            ast.parse(open(p, encoding="utf-8").read(), filename=p)
                        except SyntaxError as e:
                            print(f"  [FAIL] {rel}: {e}")
                            errors += 1
            if working_dir:
                for rel, _ in PATCHES_APP:
                    p = os.path.join(working_dir, rel)
                    if os.path.isfile(p):
                        checked += 1
                        try:
                            ast.parse(open(p, encoding="utf-8").read(), filename=p)
                        except SyntaxError as e:
                            print(f"  [FAIL] {rel}: {e}")
                            errors += 1
        if checked == 0:
            print("  [WARN] 0 modules checked (app payload missing).")
            return True
        if errors == 0:
            print(f"  -> All {checked} target modules passed AST validation.")
        else:
            print(f"  -> Verification failed with {errors} syntax error(s).")
        return errors == 0

    def get_status(self):
        print(f"[*] Wine Prefix: {self.prefix_path}")
        if not self.trees:
            print("  -> No OK-WW install tree found.")
            return
        for i, (site_packages, working_dir) in enumerate(self.trees, 1):
            if len(self.trees) > 1:
                print(f"--- Install tree {i}/{len(self.trees)} ---")
            base = site_packages or working_dir
            for rel, marker, name in [(p[0], p[1], p[2]) for p in PATCHES_GUI_FULL] + \
                                     [(p[0], p[1], p[2]) for p in PATCHES_APP_FULL]:
                target = os.path.join(site_packages, rel) if site_packages and (rel, marker, name) in PATCHES_GUI_FULL else os.path.join(working_dir or "", rel)
                # resolve base properly
                if site_packages and any(rel == g[0] for g in PATCHES_GUI_FULL):
                    target = os.path.join(site_packages, rel)
                else:
                    target = os.path.join(working_dir or "", rel)
                if not os.path.isfile(target):
                    print(f"  [ ] {name} (not installed: {rel})")
                    continue
                content = open(target, encoding="utf-8", errors="replace").read()
                is_patched = marker in content
                has_orig = os.path.isfile(target + ".orig")
                print(f"  [{'x' if is_patched else ' '}] {name} [backup: {has_orig}]")

    # ------------------ patch implementations ------------------

    def _patch_gui_packages(self, site_packages: str, source: PristineSource):
        for rel, transforms in PATCHES_GUI:
            fp = os.path.join(site_packages, rel)
            if not os.path.isfile(fp):
                continue
            self._patch_file(fp, rel, source.get(fp, rel), transforms, rel)

    def _patch_app_modules(self, working_dir: str, source: PristineSource):
        for rel, transforms in PATCHES_APP:
            fp = os.path.join(working_dir, rel)
            if not os.path.isfile(fp):
                continue
            self._patch_file(fp, rel, source.get(fp, rel), transforms, rel)


# ------------------------- patch specs -------------------------

def _t_win32_utils(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    content, m1 = PatchEngine._sub(content,
        'def isCompositionEnabled():\n    """ detect if dwm composition is enabled """\n    bResult = c_int(0)',
        'def isCompositionEnabled():\n    """ detect if dwm composition is enabled """\n    if is_wine():\n        return False\n    bResult = c_int(0)', "isCompositionEnabled guard")
    content, m2 = PatchEngine._sub(content,
        'def isGreaterEqualWin11():\n    """ determine if the windows version ≥ Win11 """\n    return isGreaterEqualWin10() and sys.getwindowsversion().build >= 22000',
        'def isGreaterEqualWin11():\n    """ determine if the windows version ≥ Win11 """\n    if is_wine():\n        return False\n    return isGreaterEqualWin10() and sys.getwindowsversion().build >= 22000', "isGreaterEqualWin11 guard")
    return content, m1 + m2


def _t_window_effect(content: str) -> Tuple[str, List[str]]:
    content, m1 = PatchEngine._sub(content,
        "from ..utils.win32_utils import isGreaterEqualWin10, isGreaterEqualWin11, isCompositionEnabled",
        "from ..utils.win32_utils import isGreaterEqualWin10, isGreaterEqualWin11, isCompositionEnabled, is_wine",
        "is_wine import")
    content, m2 = PatchEngine._sub(content,
        '        if not isGreaterEqualWin11():\n            warnings.warn("The mica effect is only available on Win11")\n            return',
        '        if not isGreaterEqualWin11() or is_wine():\n            return',
        "setMicaEffect wine guard")
    return content, m1 + m2


def _t_fluent_window(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    content, m1 = PatchEngine._sub(content,
        "        # enable mica effect on win11\n        self.setMicaEffectEnabled(True)",
        "        # enable mica effect on win11 (unless on Wine)\n        if not is_wine():\n            self.setMicaEffectEnabled(True)\n        else:\n            self._isMicaEnabled = False\n            self.setBackgroundColor(self._normalBackgroundColor())",
        "mica disable")
    content, m2 = PatchEngine._sub(content,
        "        if sys.platform != 'win32' or sys.getwindowsversion().build < 22000:\n            return",
        "        if sys.platform != 'win32' or sys.getwindowsversion().build < 22000 or is_wine():\n            self._isMicaEnabled = False\n            self.setBackgroundColor(self._normalBackgroundColor())\n            return",
        "setMicaEffectEnabled guard")
    return content, m1 + m2


def _t_window(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    content, m1 = PatchEngine._sub(content,
        "def windows_graphics_available():\n",
        "def windows_graphics_available():\n    if is_wine():\n        return False\n", "windows_graphics_available guard")
    old_get_exe = (
        "def get_exe_by_hwnd(hwnd):\n"
        "    try:\n"
        "        if not win32gui.IsWindow(hwnd):\n"
        "            return \"\", \"\", \"\"\n"
        "        _, pid = win32process.GetWindowThreadProcessId(hwnd)\n"
        "        if pid <= 0:\n"
        "            return \"\", \"\", \"\""
    )
    new_get_exe = (
        "def get_exe_by_hwnd(hwnd):\n"
        "    try:\n"
        "        if not win32gui.IsWindow(hwnd):\n"
        "            return \"\", \"\", \"\"\n"
        "        _, pid = win32process.GetWindowThreadProcessId(hwnd)\n"
        "        if pid <= 0:\n"
        "            return \"\", \"\", \"\"\n\n"
        "        try:\n"
        "            h_proc = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.PROCESS_VM_READ, False, pid)\n"
        "            if h_proc:\n"
        "                try:\n"
        "                    exe_path = win32process.GetModuleFileNameEx(h_proc, 0)\n"
        "                    if exe_path:\n"
        "                        win32api.CloseHandle(h_proc)\n"
        "                        return os.path.basename(exe_path), exe_path, \"\"\n"
        "                except Exception:\n"
        "                    pass\n"
        "                win32api.CloseHandle(h_proc)\n"
        "        except Exception:\n"
        "            pass"
    )
    content, m2 = PatchEngine._sub(content, old_get_exe, new_get_exe, "get_exe_by_hwnd query")
    old_check = (
        "        if exe_names:\n"
        "            if not name or not any((compare_path_safe(name, exe_name) or compare_path_safe(exe_name, full_path)) for exe_name in exe_names):\n"
        "                return True"
    )
    new_check = (
        "        if exe_names:\n"
        "            matched_exe = name and any((compare_path_safe(name, exe_name) or compare_path_safe(exe_name, full_path)) for exe_name in exe_names)\n"
        "            if not matched_exe:\n"
        "                if not (is_wine() and is_main_class and class_name is not None):\n"
        "                    return True"
    )
    content, m3 = PatchEngine._sub(content, old_check, new_check, "exe-name matching")
    return content, m1 + m2 + m3


def _t_translation(content: str) -> Tuple[str, List[str]]:
    content, m1 = PatchEngine._sub(content,
        "return gettext.translation('ok', dir_i18n, languages=fallback_list)",
        "return gettext.translation('ok', dir_i18n, languages=fallback_list, fallback=True)",
        "ok fallback")
    content, m2 = PatchEngine._sub(content,
        "return gettext.translation('ocr', dir_i18n, languages=fallback_list)",
        "return gettext.translation('ocr', dir_i18n, languages=fallback_list, fallback=True)",
        "ocr fallback")
    return content, m1 + m2


def _t_explorer(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    content, m1 = PatchEngine._sub(content,
        "    if _focus_existing_explorer_window(folder, item_name):\n        logger.info(f'Explorer focused existing window: folder={str(folder)!r}')\n        return True",
        "    if is_wine():\n        os.startfile(str(folder), 'explore')\n        logger.info('Explorer launch request completed (Wine)')\n        return True\n    if _focus_existing_explorer_window(folder, item_name):\n        logger.info(f'Explorer focused existing window: folder={str(folder)!r}')\n        return True",
        "wine startfile")
    return content, m1


def _t_process(content: str) -> Tuple[str, List[str]]:
    if "def is_wine():" not in content:
        content = WINE_FUNC + content
    content, m1 = PatchEngine._sub(content,
        "def get_first_gpu_free_memory_mib():\n",
        "def get_first_gpu_free_memory_mib():\n    if is_wine():\n        return -1\n",
        "gpu guard")
    return content, m1


def _t_config(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    old_calc = (
        "def calculate_pc_exe_path(running_path):\n"
        "    if running_path is None:\n"
        "        return _find_most_recently_run_pc_exe() or _find_pc_exe_from_registry()\n"
        "    game_exe_folder = Path(running_path).parents[3]\n"
        "    return str(game_exe_folder / \"Wuthering Waves.exe\")"
    )
    new_calc = (
        "def calculate_pc_exe_path(running_path):\n"
        "    if running_path is None:\n"
        "        if is_wine():\n"
        "            return \"steam://rungameid/3513350\"\n"
        "        standalone = _find_most_recently_run_pc_exe() or _find_pc_exe_from_registry()\n"
        "        if standalone:\n"
        "            return standalone\n"
        "        return \"steam://rungameid/3513350\"\n"
        "    game_exe_folder = Path(running_path).parents[3]\n"
        "    return str(game_exe_folder / \"Wuthering Waves.exe\")"
    )
    content, m1 = PatchEngine._sub(content, old_calc, new_calc, "steam uri fallback")
    return content, m1


def _t_bitblt(content: str) -> Tuple[str, List[str]]:
    content, m1 = PatchEngine._sub(content,
        "def capture_by_bitblt(context, hwnd, width, height, x, y, render_full_content):\n    if hwnd <= 0 or width <= 0 or height <= 0:\n        logger.error(f'capture_by_bitblt invalid params: hwnd={hwnd}, w={width}, h={height}')\n        return None",
        "def capture_by_bitblt(context, hwnd, width, height, x, y, render_full_content):\n    if hwnd <= 0 or width <= 0 or height <= 0:\n        return None\n    if not win32gui.IsWindow(hwnd):\n        clean_up_bitblt(context)\n        return None",
        "hwnd validation")
    return content, m1


def _t_startcard(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    peek_block = (
        "        msg = wintypes.MSG()\n"
        "        if windll.user32.PeekMessageW(byref(msg), None, 0, 0, 1):\n"
        "            if msg.message == 0x0312:  # WM_HOTKEY\n"
        "                logger.debug(f'hotkey pressed {msg}')\n"
        "                if msg.wParam == 999:\n"
        "                    self.clicked()\n"
        "\n"
        "        self.handler.post(self.check_hotkey, 0.1)"
    )
    content, m1 = PatchEngine._sub(content, peek_block,
        "        self.handler.post(self.check_hotkey, 0.1)",
        "PeekMessageW poll removal")
    rebind_block = (
        "    def rebind_hotkey(self, hotkey):\n"
        "        windll.user32.UnregisterHotKey(None, 999)\n"
        "        vk_map = {'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B}\n"
        "\n"
        "        if hotkey and hotkey != 'None' and hotkey in vk_map:\n"
        "            if not windll.user32.RegisterHotKey(None, 999, 0, vk_map[hotkey]):\n"
        "                logger.error(f\"Failed to register hotkey {hotkey}\")\n"
        "        else:\n"
        "            logger.debug(f\"Hotkey disabled or invalid: {hotkey}\")"
    )
    content, m2 = PatchEngine._sub(content, rebind_block,
        "    def rebind_hotkey(self, hotkey):\n"
        "        if is_wine():\n"
        "            return\n"
        "        logger.debug('hotkey binding skipped on Wine')",
        "hotkey registration removal")
    return content, m1 + m2


# (relpath, transform) — GUI site-packages patches
PATCHES_GUI: List[Tuple[str, Callable]] = [
    ("qframelesswindow/utils/win32_utils.py", _t_win32_utils),
    ("qframelesswindow/windows/window_effect.py", _t_window_effect),
    ("qfluentwidgets/window/fluent_window.py", _t_fluent_window),
]

# (relpath, transform) — working-dir app patches
PATCHES_APP: List[Tuple[str, Callable]] = [
    ("ok/util/window.py", _t_window),
    ("ok/core/translation.py", _t_translation),
    ("ok/util/explorer.py", _t_explorer),
    ("ok/util/process.py", _t_process),
    ("config.py", _t_config),
    ("ok/device/capture_methods/bitblt_utils.py", _t_bitblt),
    ("ok/ui/qt/start/StartCard.py", _t_startcard),
]

# (relpath, marker, name) for status display
PATCHES_GUI_FULL = [
    ("qframelesswindow/utils/win32_utils.py", "is_wine", "qframelesswindow Mica/Glass bypass"),
    ("qframelesswindow/windows/window_effect.py", "is_wine", "qframelesswindow window_effect"),
    ("qfluentwidgets/window/fluent_window.py", "is_wine", "qfluentwidgets Solid Backgrounds"),
]
PATCHES_APP_FULL = [
    ("ok/util/window.py", "is_wine", "Window Capture & Exe Matching"),
    ("ok/core/translation.py", "fallback=True", "Translation Fallback"),
    ("ok/util/explorer.py", "is_wine", "Explorer Launch Optimization"),
    ("ok/util/process.py", "is_wine", "GPU / Process Info Guard"),
    ("config.py", "steam://rungameid/3513350", "Anti-Cheat Safe Game Launcher"),
    ("ok/device/capture_methods/bitblt_utils.py", "clean_up_bitblt(context)", "BitBlt HWND Validation"),
    ("ok/ui/qt/start/StartCard.py", "hotkey binding skipped on Wine", "Start Hotkey Thread Guard"),
]


def resolve_prefix(target: str) -> Optional[str]:
    if "compatdata" in target and "pfx" in target:
        return target if target.endswith("pfx") else target[:target.find("pfx") + 3]
    if os.path.isdir(os.path.join(target, "pfx")):
        return os.path.join(target, "pfx")
    curr = target
    while curr and curr != "/":
        if os.path.basename(curr) == "pfx":
            return curr
        curr = os.path.dirname(curr)
    return None


def fix_icu_dlls(prefix_path: str):
    """Ensure ICU DLL aliases so PySide6/Qt6Core load under Wine."""
    for arch in ("system32", "syswow64"):
        d = os.path.join(prefix_path, "drive_c", "windows", arch)
        icu = os.path.join(d, "icu.dll")
        for alias in ("icuuc.dll", "icuin.dll"):
            p = os.path.join(d, alias)
            if os.path.isfile(icu) and not os.path.isfile(p):
                shutil.copy2(icu, p)


def main():
    parser = argparse.ArgumentParser(description="Quilt-style idempotent Wine/Proton patcher for OK-WuWa")
    parser.add_argument("prefix", help="Path to Wine prefix or compatdata directory")
    parser.add_argument("--revert", "--undo", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--offline", action="store_true", help="Skip upstream fetch; use .orig backups only")

    args = parser.parse_args()
    target = os.path.abspath(args.prefix)

    pfx_path = resolve_prefix(target)
    if not pfx_path or not os.path.isdir(pfx_path):
        print(f"Error: Could not determine Wine prefix from '{target}'")
        sys.exit(1)

    engine = PatchEngine(pfx_path, offline=args.offline)
    fix_icu_dlls(pfx_path)

    if args.revert:
        engine.revert_patches()
    elif args.status:
        engine.get_status()
    elif args.verify:
        engine.verify()
    else:
        if not engine.apply_patches():
            sys.exit(1)


if __name__ == "__main__":
    main()
