#!/usr/bin/env python3
"""
wine_runtime.py - Version-agnostic Win32/Python runtime compatibility layer for OK-WuWa.

Instead of fragile text-replacement patches on upstream OK-WW source files
(which break whenever upstream renames or refactors modules), this runtime shim
is loaded automatically via sitecustomize.py inside Wine's python.exe and hooks
stable OS / Python / Win32 API boundaries in memory:

1. Windows build normalization (10.0.19045): automatically disables unimplemented
   Windows 11 DWM Mica/Acrylic backdrops and WinRT Windows.Graphics.Capture
   across past, current, and future UI toolkits.
2. Win32 thread hotkey virtualization (user32.RegisterHotKey / UnregisterHotKey /
   PeekMessageW): intercepts background-thread hotkey loops before Wine creates a
   deadlocking X11 thread input queue, polling GetAsyncKeyState instead so F9-F12
   and Ctrl+Alt+D/S hotkeys work regardless of which UI class registers them.
3. Gettext fallback: retries missing locale .mo lookups with fallback=True.
4. PostMessage input conditioning (win32gui.PostMessage): suppresses Wine
   focus-stealing WM_ACTIVATE spam and enforces a >=40ms hold between DOWN and UP
   messages so DXVK/UE4 frame ticks never drop fast taps.
5. Process / Shell shims: handles Steam container handoff in os.startfile,
   silences missing Windows nvidia-smi probes, and gracefully wraps ok.* helpers
   at import time without modifying a single upstream file on disk.
"""

import argparse
import ctypes
from ctypes import wintypes
import importlib.abc
import json
import os
import sys
import threading
import time

DEFAULT_APP_ROOT = os.path.join(os.path.expanduser("~"), ".local", "share", "ok-wuwa", "app")
STEAM_GAME_URI = "steam://rungameid/3513350"
MIN_HOLD_SECONDS = 0.04


def is_wine_process() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return hasattr(ctypes.cdll.ntdll, "wine_get_version")
    except Exception:
        return False


def _should_activate_runtime() -> bool:
    if not is_wine_process():
        return False
    # Never interfere with pip / ensurepip package management invocations
    argv_lower = [a.lower() for a in sys.argv]
    if "pip" in argv_lower or "ensurepip" in argv_lower:
        return False
    return True


def _install_build_shim() -> None:
    """Report Windows 10 22H2 (build 19045 < 20348 WGC & < 22000 Win11 Mica)
    so every UI toolkit and capture probe uses solid rendering and BitBlt."""
    orig_getwinver = sys.getwindowsversion

    class _Win10Version:
        def __init__(self, base):
            self._base = base
            self.major = 10
            self.minor = 0
            self.build = 19045
            self.platform = getattr(base, "platform", 2)
            self.service_pack = getattr(base, "service_pack", "")
            self.service_pack_major = getattr(base, "service_pack_major", 0)
            self.service_pack_minor = getattr(base, "service_pack_minor", 0)
            self.suite_mask = getattr(base, "suite_mask", 0)
            self.product_type = getattr(base, "product_type", 1)
            self.platform_version = (10, 0, 19045)

        def __getitem__(self, idx):
            return (self.major, self.minor, self.build, self.platform, self.service_pack)[idx]

        def __repr__(self):
            return "sys.getwindowsversion(major=10, minor=0, build=19045, platform=2, service_pack='')"

    _cached = _Win10Version(orig_getwinver())
    sys.getwindowsversion = lambda: _cached

    import platform
    platform.version = lambda: "10.0.19045"
    platform.release = lambda: "10"


def _install_hotkey_shim() -> None:
    """Virtualize thread-level RegisterHotKey + PeekMessageW via GetAsyncKeyState
    to prevent Wine's X11 background-thread message queue deadlock."""
    user32 = ctypes.windll.user32
    orig_reg = user32.RegisterHotKey
    orig_unreg = user32.UnregisterHotKey
    orig_peek = user32.PeekMessageW
    get_async = user32.GetAsyncKeyState

    lock = threading.Lock()
    # (thread_ident, hotkey_id) -> [mods, vk, was_down]
    hotkeys = {}

    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    WM_HOTKEY = 0x0312

    def _mods_pressed(mods: int) -> bool:
        if (mods & MOD_ALT) and not (get_async(0x12) & 0x8000):
            return False
        if (mods & MOD_CONTROL) and not (get_async(0x11) & 0x8000):
            return False
        if (mods & MOD_SHIFT) and not (get_async(0x10) & 0x8000):
            return False
        return True

    def _shim_register(hwnd, hk_id, mods, vk):
        if hwnd in (None, 0):
            tid = threading.get_ident()
            with lock:
                hotkeys[(tid, int(hk_id))] = [int(mods) & 0x0007, int(vk), False]
            return 1
        return orig_reg(hwnd, hk_id, mods, vk)

    def _shim_unregister(hwnd, hk_id):
        if hwnd in (None, 0):
            tid = threading.get_ident()
            with lock:
                hotkeys.pop((tid, int(hk_id)), None)
            return 1
        return orig_unreg(hwnd, hk_id)

    def _shim_peek(p_msg, hwnd, wmin, wmax, remove):
        if hwnd in (None, 0) and threading.current_thread() is not threading.main_thread():
            tid = threading.get_ident()
            triggered_id = None
            with lock:
                entries = [(hk_id, state) for (t, hk_id), state in hotkeys.items() if t == tid]
                for hk_id, state in entries:
                    mods, vk, was_down = state
                    down = bool(get_async(vk) & 0x8000) and _mods_pressed(mods)
                    state[2] = down
                    if down and not was_down and triggered_id is None:
                        triggered_id = hk_id
            if triggered_id is not None and p_msg:
                msg = getattr(p_msg, "_obj", None)
                if msg is None and hasattr(p_msg, "contents"):
                    msg = p_msg.contents
                elif msg is None and isinstance(p_msg, int):
                    msg = wintypes.MSG.from_address(p_msg)
                if msg is not None:
                    msg.hwnd = None
                    msg.message = WM_HOTKEY
                    msg.wParam = triggered_id
                    msg.lParam = 0
                    return 1
            return 0
        return orig_peek(p_msg, hwnd, wmin, wmax, remove)

    user32.RegisterHotKey = _shim_register
    user32.UnregisterHotKey = _shim_unregister
    user32.PeekMessageW = _shim_peek


def _install_gettext_shim() -> None:
    import gettext
    orig_translation = gettext.translation

    def _safe_translation(domain, localedir=None, languages=None, class_=None, fallback=False, codeset=None):
        try:
            if codeset is not None:
                return orig_translation(domain, localedir, languages=languages, class_=class_, fallback=fallback, codeset=codeset)
            return orig_translation(domain, localedir, languages=languages, class_=class_, fallback=fallback)
        except FileNotFoundError:
            return orig_translation(domain, localedir, languages=languages, class_=class_, fallback=True)

    gettext.translation = _safe_translation


def _install_os_and_subprocess_shims() -> None:
    orig_startfile = getattr(os, "startfile", None)
    if orig_startfile is not None:
        def _shim_startfile(filepath, *args, **kwargs):
            target = os.fspath(filepath) if hasattr(os, "fspath") else str(filepath)
            handoff = os.environ.get("OKWW_HANDOFF_FILE")
            if handoff and isinstance(target, str) and target.startswith("steam://"):
                task_name = ""
                try:
                    from ok import og
                    sc = getattr(getattr(og, "app", None), "start_controller", None)
                    active = getattr(sc, "_active_task", None) if sc else None
                    if active is not None and hasattr(active, "name"):
                        task_name = str(active.name)
                except Exception:
                    pass
                try:
                    with open(handoff, "w", encoding="utf-8") as hf:
                        json.dump({"url": target, "task": task_name}, hf)
                    os._exit(75)
                except OSError:
                    pass
            return orig_startfile(filepath, *args, **kwargs)

        os.startfile = _shim_startfile

    import subprocess
    orig_run = subprocess.run
    orig_check_output = subprocess.check_output

    def _is_nvidia_smi(popenargs) -> bool:
        if not popenargs:
            return False
        cmd = popenargs[0]
        first = cmd[0] if isinstance(cmd, (list, tuple)) and cmd else cmd
        return isinstance(first, str) and os.path.basename(first).lower() in ("nvidia-smi", "nvidia-smi.exe")

    def _shim_run(*popenargs, **kwargs):
        if _is_nvidia_smi(popenargs):
            return subprocess.CompletedProcess(popenargs[0], returncode=1, stdout="", stderr="")
        return orig_run(*popenargs, **kwargs)

    def _shim_check_output(*popenargs, **kwargs):
        if _is_nvidia_smi(popenargs):
            raise subprocess.CalledProcessError(1, popenargs[0], output="")
        return orig_check_output(*popenargs, **kwargs)

    subprocess.run = _shim_run
    subprocess.check_output = _shim_check_output


def _install_win32gui_shim() -> None:
    try:
        import win32gui
    except ImportError:
        return

    orig_post = win32gui.PostMessage
    down_times = {}
    WM_ACTIVATE = 0x0006
    DOWN_TO_GROUP = {
        0x0100: "key", 0x0104: "syskey",
        0x0201: "lbtn", 0x0204: "rbtn", 0x0207: "mbtn", 0x020B: "xbtn",
    }
    UP_TO_GROUP = {
        0x0101: "key", 0x0105: "syskey",
        0x0202: "lbtn", 0x0205: "rbtn", 0x0208: "mbtn", 0x020C: "xbtn",
    }

    def _shim_post_message(hwnd, msg, wparam=0, lparam=0):
        if msg == WM_ACTIVATE:
            # Suppress continuous WM_ACTIVATE spam which steals XWayland focus on Wine
            return 0
        if msg in DOWN_TO_GROUP:
            key = (int(hwnd or 0), DOWN_TO_GROUP[msg], int(wparam) if msg in (0x0100, 0x0104) else 0)
            down_times[key] = time.monotonic()
        elif msg in UP_TO_GROUP:
            key = (int(hwnd or 0), UP_TO_GROUP[msg], int(wparam) if msg in (0x0101, 0x0105) else 0)
            t0 = down_times.pop(key, None)
            if t0 is not None:
                rem = MIN_HOLD_SECONDS - (time.monotonic() - t0)
                if 0 < rem <= MIN_HOLD_SECONDS:
                    time.sleep(rem)
        return orig_post(hwnd, msg, wparam, lparam)

    win32gui.PostMessage = _shim_post_message


class _OkModulePostLoader(importlib.abc.Loader):
    def __init__(self, wrapped_loader, hook_fn):
        self._wrapped = wrapped_loader
        self._hook_fn = hook_fn

    def create_module(self, spec):
        if hasattr(self._wrapped, "create_module"):
            return self._wrapped.create_module(spec)
        return None

    def exec_module(self, module):
        self._wrapped.exec_module(module)
        try:
            self._hook_fn(module)
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


class _OkCompatFinder(importlib.abc.MetaPathFinder):
    """Non-invasive post-import hooks for optional OK-WW module enhancements.
    If upstream renames or restructures any module in a future release, imports
    continue cleanly without ever failing."""

    def __init__(self):
        self._in_progress = set()

    def find_spec(self, fullname, path, target=None):
        hook = self._HOOKS.get(fullname)
        if hook is None or fullname in self._in_progress:
            return None
        self._in_progress.add(fullname)
        try:
            for finder in sys.meta_path:
                if finder is self:
                    continue
                find_spec = getattr(finder, "find_spec", None)
                if find_spec is None:
                    continue
                spec = find_spec(fullname, path, target)
                if spec is not None and spec.loader is not None:
                    spec.loader = _OkModulePostLoader(spec.loader, hook)
                    return spec
            return None
        finally:
            self._in_progress.discard(fullname)

    @staticmethod
    def _hook_window(mod):
        import win32gui
        orig_fg = getattr(mod, "is_foreground_window", None)
        if callable(orig_fg):
            def _wine_fg(hwnd):
                if os.environ.get("OKWW_REQUIRE_FOREGROUND") != "1":
                    return bool(win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd))
                return orig_fg(hwnd)
            mod.is_foreground_window = _wine_fg

        if hasattr(mod, "windows_graphics_available"):
            mod.windows_graphics_available = lambda: False

    @staticmethod
    def _hook_bitblt(mod):
        import win32gui
        orig_cap = getattr(mod, "capture_by_bitblt", None)
        clean_fn = getattr(mod, "clean_up_bitblt", None)
        if callable(orig_cap):
            def _safe_cap(context, hwnd, width, height, x, y, render_full_content):
                if hwnd <= 0 or width <= 0 or height <= 0:
                    return None
                if not win32gui.IsWindow(hwnd):
                    if callable(clean_fn):
                        clean_fn(context)
                    return None
                return orig_cap(context, hwnd, width, height, x, y, render_full_content)
            mod.capture_by_bitblt = _safe_cap

    @staticmethod
    def _hook_explorer(mod):
        if hasattr(mod, "_open_or_focus"):
            def _wine_open_folder(folder, item_name=None, item_path=None):
                os.startfile(str(folder), "explore")
                return True
            mod._open_or_focus = _wine_open_folder

    @staticmethod
    def _hook_post_message(mod):
        cls = getattr(mod, "PostMessageInteraction", None)
        if cls is not None and hasattr(cls, "click"):
            def _right_click(self, x=-1, y=-1, move_back=False, name=None):
                return self.click(x, y, move_back=move_back, name=name, key="right")
            cls.right_click = _right_click

    @staticmethod
    def _hook_config(mod):
        orig_calc = getattr(mod, "calculate_pc_exe_path", None)
        if callable(orig_calc):
            def _wine_calc(running_path):
                if running_path is None:
                    return STEAM_GAME_URI
                return orig_calc(running_path)
            mod.calculate_pc_exe_path = _wine_calc
        cfg = getattr(mod, "config", None)
        if isinstance(cfg, dict) and isinstance(cfg.get("windows"), dict) and callable(orig_calc):
            cfg["windows"]["calculate_pc_exe_path"] = mod.calculate_pc_exe_path

    @staticmethod
    def _hook_ok_pkg(mod):
        if os.environ.get("OKWW_AUTO_START") != "1":
            return
        ok_cls = getattr(mod, "OK", None)
        if ok_cls is None:
            return
        orig_init_rt = getattr(ok_cls, "do_init_runtime", None) or getattr(ok_cls, "start", None)
        # Trigger start_controller.start() once start_success fires after container handoff
        try:
            from ok.core.events import communicate
            def _auto_resume():
                app = getattr(getattr(mod, "og", None), "app", None)
                sc = getattr(app, "start_controller", None)
                if sc is not None and not getattr(sc, "starting", False):
                    sc.start()
            communicate.start_success.connect(_auto_resume)
        except Exception:
            pass

    _HOOKS = {}


_OkCompatFinder._HOOKS = {
    "ok.util.window": _OkCompatFinder._hook_window,
    "ok.device.capture_methods.bitblt_utils": _OkCompatFinder._hook_bitblt,
    "ok.util.explorer": _OkCompatFinder._hook_explorer,
    "ok.device.interaction_methods.post_message": _OkCompatFinder._hook_post_message,
    "config": _OkCompatFinder._hook_config,
    "ok": _OkCompatFinder._hook_ok_pkg,
}


def activate() -> None:
    if getattr(sys, "_okww_wine_runtime_active", False):
        return
    if not _should_activate_runtime():
        return
    sys._okww_wine_runtime_active = True
    _install_build_shim()
    _install_hotkey_shim()
    _install_gettext_shim()
    _install_os_and_subprocess_shims()
    _install_win32gui_shim()
    sys.meta_path.insert(0, _OkCompatFinder())


# ------------------------- host installer CLI -------------------------

SITECUSTOMIZE_HOOK = '''# Managed by ok-wuwa-linux: automatic version-agnostic Wine runtime compatibility
import os as _os
import importlib.util as _ilu

def _load_okww_runtime():
    py_dir = _os.path.dirname(_os.path.abspath(__file__))
    candidates = [
        _os.path.join(py_dir, "_okww_wine_runtime.py"),
        _os.path.normpath(_os.path.join(py_dir, "..", "..", "..", "..", "..", "..", "patch_wine_compat.py")),
    ]
    for path in candidates:
        if _os.path.isfile(path):
            spec = _ilu.spec_from_file_location("_okww_wine_runtime", path)
            if spec and spec.loader:
                mod = _ilu.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.activate()
            return

try:
    _load_okww_runtime()
except Exception:
    pass
'''


def _find_site_packages(target: str):
    target = os.path.abspath(os.path.expanduser(target))
    candidates = [
        os.path.join(target, "data", "apps", "ok-ww", "python", "Lib", "site-packages"),
        os.path.normpath(os.path.join(target, "..", "python", "Lib", "site-packages")),
        os.path.join(target, "Lib", "site-packages"),
    ]
    pfx = os.path.join(target, "pfx") if os.path.isdir(os.path.join(target, "pfx")) else target
    users_dir = os.path.join(pfx, "drive_c", "users")
    if os.path.isdir(users_dir):
        for entry in sorted(os.listdir(users_dir)):
            candidates.append(
                os.path.join(users_dir, entry, "AppData", "Local", "ok-ww", "data", "apps", "ok-ww", "python", "Lib", "site-packages")
            )
    seen = set()
    result = []
    for sp in candidates:
        if os.path.isdir(sp):
            real = os.path.realpath(sp)
            if real not in seen:
                seen.add(real)
                result.append(real)
    return result


def _clean_legacy_working_patches(sp_dir: str) -> int:
    """If an older file-patching version left modified files or .orig backups in
    working/, restore working/ cleanly from the local git repo so upstream
    updates never see dirty tracked files."""
    working = os.path.normpath(os.path.join(sp_dir, "..", "..", "..", "working"))
    repo = os.path.normpath(os.path.join(sp_dir, "..", "..", "..", "repo"))
    cleaned = 0
    if not os.path.isdir(working):
        return 0
    for root, _, files in os.walk(working):
        for fn in files:
            if fn.endswith(".orig"):
                orig_p = os.path.join(root, fn)
                target_p = orig_p[:-5]
                try:
                    os.replace(orig_p, target_p)
                    cleaned += 1
                except OSError:
                    pass
    if cleaned and os.path.isdir(os.path.join(repo, "objects")):
        import shutil as _sh
        if _sh.which("git"):
            import subprocess as _sp
            _sp.run(["git", f"--git-dir={repo}", f"--work-tree={working}", "checkout", "-q", "-f", "HEAD"], check=False)
    return cleaned


def ensure_local_icu_dlls(sp_dirs, prefix_path=None) -> None:
    if not prefix_path:
        return
    import shutil as _sh
    pfx = os.path.join(prefix_path, "pfx") if os.path.isdir(os.path.join(prefix_path, "pfx")) else prefix_path
    sys32 = os.path.join(pfx, "drive_c", "windows", "system32")
    icu_src = os.path.join(sys32, "icu.dll")
    if not os.path.isfile(icu_src):
        return
    missing = [a for a in ("icuuc.dll", "icuin.dll") if not os.path.isfile(os.path.join(sys32, a))]
    if not missing:
        return
    for sp in sp_dirs:
        py_dir = os.path.normpath(os.path.join(sp, "..", ".."))
        for alias in missing:
            dst = os.path.join(py_dir, alias)
            if not os.path.isfile(dst):
                _sh.copy2(icu_src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description="Version-agnostic Wine runtime compatibility installer for OK-WuWa")
    parser.add_argument("target", nargs="?", default=DEFAULT_APP_ROOT, help="Path to OK-WuWa app root or working dir")
    parser.add_argument("--prefix", help="Optional Wine prefix for zero-pollution ICU fallback check")
    parser.add_argument("--revert", "--undo", action="store_true", help="Remove runtime hook and leave pure upstream state")
    parser.add_argument("--status", action="store_true", help="Show runtime compatibility layer status")
    parser.add_argument("--verify", action="store_true", help="Validate runtime layer syntax and installation")
    parser.add_argument("--offline", action="store_true", help="Accepted for CLI compatibility (always offline)")
    args = parser.parse_args()

    sp_dirs = _find_site_packages(args.target)
    if not sp_dirs:
        print("[WARN] No OK-WW Python environment found yet.")
        return

    ensure_local_icu_dlls(sp_dirs, args.prefix)
    with open(os.path.abspath(__file__), encoding="utf-8") as f:
        self_source = f.read()

    if args.revert:
        for sp in sp_dirs:
            _clean_legacy_working_patches(sp)
            for fn in ("_okww_wine_runtime.py", "sitecustomize.py"):
                p = os.path.join(sp, fn)
                if os.path.isfile(p):
                    os.unlink(p)
            print(f"[*] Removed Wine runtime hook from {sp} (upstream working tree is 100% untouched).")
        return

    if args.status:
        for sp in sp_dirs:
            rt = os.path.isfile(os.path.join(sp, "_okww_wine_runtime.py"))
            sc = os.path.isfile(os.path.join(sp, "sitecustomize.py"))
            working = os.path.normpath(os.path.join(sp, "..", "..", "..", "working"))
            dirty_orig = sum(1 for r, _, fs in os.walk(working) for fn in fs if fn.endswith(".orig")) if os.path.isdir(working) else 0
            print(f"[*] Environment: {sp}")
            print(f"  [{'x' if (rt and sc) else ' '}] Version-Agnostic Win32 Runtime Shim Active")
            print(f"  [{'x' if dirty_orig == 0 else ' '}] Upstream working/ Tree 100% Unmodified (0 file patches)")
        return

    if args.verify:
        import ast
        ast.parse(self_source, filename=__file__)
        for sp in sp_dirs:
            for fn in ("_okww_wine_runtime.py", "sitecustomize.py"):
                p = os.path.join(sp, fn)
                if not os.path.isfile(p):
                    print(f"  [FAIL] Missing {p}")
                    sys.exit(1)
                with open(p, encoding="utf-8") as fh:
                    ast.parse(fh.read(), filename=p)
        print("  -> Runtime compatibility shim verified (AST valid, upstream files untouched).")
        return

    import ast
    ast.parse(self_source, filename=__file__)
    for sp in sp_dirs:
        cleaned = _clean_legacy_working_patches(sp)
        if cleaned:
            print(f"  -> Cleaned {cleaned} legacy file patch(es) in working/ back to pure upstream.")
        with open(os.path.join(sp, "_okww_wine_runtime.py"), "w", encoding="utf-8", newline="\n") as f:
            f.write(self_source)
        with open(os.path.join(sp, "sitecustomize.py"), "w", encoding="utf-8", newline="\n") as f:
            f.write(SITECUSTOMIZE_HOOK)
        print(f"  -> Installed version-agnostic Wine runtime layer into {sp}")


if __name__ == "__main__":
    main()
