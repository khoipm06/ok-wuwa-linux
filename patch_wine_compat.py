#!/usr/bin/env python3
"""
Wine / Proton Compatibility Patcher for OK-Wuthering-Waves

Features:
- Transactional file patching with automatic .orig pristine backups.
- Strict syntax and AST verification.
- Idempotent: Re-running always starts from .orig and never stacks patches.
- Full Revert / Undo support (--revert) to restore 100% stock files.
- Patch verification and status reporting (--status, --verify).
- Patches every ok-ww install tree in the prefix (Proton prefixes can
  contain multiple hardlinked user dirs, e.g. steamuser + account user).
"""

import argparse
import ast
import os
import shutil
import sys
from typing import List, Optional, Tuple


WINE_FUNC = (
    "def is_wine():\n"
    "    try:\n"
    "        import ctypes\n"
    "        return hasattr(ctypes.cdll.ntdll, 'wine_get_version')\n"
    "    except Exception:\n"
    "        return False\n\n"
)


class PatchEngine:
    def __init__(self, prefix_path: str):
        self.prefix_path = os.path.abspath(prefix_path)
        # (site_packages, working_dir) for every ok-ww install tree found.
        self.trees: List[Tuple[Optional[str], Optional[str]]] = self._locate_directories()

    def _locate_directories(self) -> List[Tuple[Optional[str], Optional[str]]]:
        users_dir = os.path.join(self.prefix_path, "drive_c", "users")
        trees: List[Tuple[Optional[str], Optional[str]]] = []
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
    def site_packages(self) -> Optional[str]:
        return self.trees[0][0] if self.trees else None

    @property
    def working_dir(self) -> Optional[str]:
        return self.trees[0][1] if self.trees else None

    # ------------------ Core file helpers ------------------

    @staticmethod
    def _safe_write_python(file_path: str, content: str) -> bool:
        """Validate Python syntax via AST before writing to disk."""
        try:
            ast.parse(content, filename=file_path)
        except SyntaxError as e:
            print(f"  [ERROR] Syntax validation failed for {file_path}: {e}")
            return False

        temp_path = file_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(temp_path, file_path)
        return True

    def _ensure_backup(self, file_path: str):
        """Create a .orig backup if it does not already exist."""
        backup_path = file_path + ".orig"
        if not os.path.isfile(backup_path) and os.path.isfile(file_path):
            shutil.copy2(file_path, backup_path)

    def _get_pristine_content(self, file_path: str) -> Optional[str]:
        """Read content from .orig if available, otherwise from original file."""
        backup_path = file_path + ".orig"
        target_path = backup_path if os.path.isfile(backup_path) else file_path
        if not os.path.isfile(target_path):
            return None
        with open(target_path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _sub(content: str, old: str, new: str, label: str) -> str:
        """Replace old with new; warn loudly when the patch site is missing.

        Every patch below starts from pristine (.orig) content, so a missed
        match means the app changed upstream and the patch site is dead.
        """
        if old not in content:
            print(f"  [WARN] Patch site not found for {label}")
        return content.replace(old, new)

    # ------------------ Commands ------------------

    def apply_patches(self) -> bool:
        """Apply all compatibility patches idempotently with AST validation."""
        print(f"[*] Target Wine Prefix: {self.prefix_path}")
        if not self.trees:
            print("[WARN] No OK-WW installation found in prefix (python/ or working/ missing).")
            return True
        for i, (site_packages, working_dir) in enumerate(self.trees, 1):
            if len(self.trees) > 1:
                print(f"[*] Install tree {i}/{len(self.trees)}")
            if site_packages:
                print(f"[1/3] Patching GUI framework packages in {site_packages}...")
                self._patch_qframelesswindow(site_packages)
                self._patch_qfluentwidgets(site_packages)
            else:
                print("[WARN] Python site-packages directory not found in this tree.")
            if working_dir:
                print(f"[2/3] Patching application modules in {working_dir}...")
                self._patch_app_modules(working_dir)
            else:
                print("[WARN] OK-WW working directory (main.py) not found in this tree.")
        print("[3/3] Verifying patched files...")
        return self.verify()

    def revert_patches(self) -> bool:
        """Revert all patches and restore pristine .orig files with corruption checking."""
        print(f"[*] Reverting patches in Wine Prefix: {self.prefix_path}")
        reverted_count = 0
        corrupted_count = 0
        users_dir = os.path.join(self.prefix_path, "drive_c", "users")
        if os.path.isdir(users_dir):
            for root, _, files in os.walk(users_dir):
                for f in files:
                    if f.endswith(".orig"):
                        orig_path = os.path.join(root, f)
                        target_path = orig_path[:-5]

                        # Corruption check on pristine backup before restoring
                        if orig_path.endswith(".py.orig"):
                            try:
                                with open(orig_path, "r", encoding="utf-8") as bf:
                                    ast.parse(bf.read(), filename=orig_path)
                            except Exception as e:
                                print(f"  [WARN] Backup file {orig_path} failed syntax check: {e}")
                                corrupted_count += 1

                        os.replace(orig_path, target_path)
                        print(f"  -> Restored: {os.path.relpath(target_path, self.prefix_path)}")
                        reverted_count += 1

        if corrupted_count > 0:
            print(f"[!] Revert completed with {corrupted_count} potential backup anomaly/anomalies.")
        else:
            print(f"[*] Successfully reverted {reverted_count} file(s) to pristine condition.")
        return True

    # ------------------ Status / Verify ------------------

    def get_status(self):
        """Report the status of each patch."""
        print(f"[*] Wine Prefix: {self.prefix_path}")
        if not self.trees:
            print("  -> No OK-WW install tree found (python/ or working/ missing).")
            return
        for i, (site_packages, working_dir) in enumerate(self.trees, 1):
            if len(self.trees) > 1:
                print(f"--- Install tree {i}/{len(self.trees)} ---")
            print(f"  -> Site Packages: {site_packages or 'Not Found'}")
            print(f"  -> Working Dir:   {working_dir or 'Not Found'}")
            print("  --- Patch Status Checklist ---")

            if site_packages:
                wu_path = os.path.join(site_packages, "qframelesswindow", "utils", "win32_utils.py")
                is_patched = os.path.isfile(wu_path) and "is_wine" in open(wu_path, "r", encoding="utf-8").read()
                has_bak = os.path.isfile(wu_path + ".orig")
                print(f"  [{'x' if is_patched else ' '}] qframelesswindow (Mica/Glass bypass) [backup: {has_bak}]")

                fw_path = os.path.join(site_packages, "qfluentwidgets", "window", "fluent_window.py")
                is_patched = os.path.isfile(fw_path) and "is_wine" in open(fw_path, "r", encoding="utf-8").read()
                has_bak = os.path.isfile(fw_path + ".orig")
                print(f"  [{'x' if is_patched else ' '}] qfluentwidgets (Solid Backgrounds) [backup: {has_bak}]")
            else:
                print("  [ ] qframelesswindow (Python environment not installed)")
                print("  [ ] qfluentwidgets (Python environment not installed)")

            if working_dir:
                for mod_rel, marker, name in [
                    ("ok/util/window.py", "is_wine", "Window Capture & Exe Matching"),
                    ("ok/core/translation.py", "fallback=True", "Translation Fallback"),
                    ("ok/util/explorer.py", "is_wine", "Explorer Launch Optimization"),
                    ("ok/util/process.py", "is_wine", "GPU / Process Info Guard"),
                    ("config.py", "steam://rungameid/3513350", "Anti-Cheat Safe Game Launcher"),
                    ("ok/device/capture_methods/bitblt_utils.py", "clean_up_bitblt(context)", "BitBlt HWND Validation"),
                    ("ok/ui/qt/start/StartCard.py", "UnregisterHotKey(hwnd, 999)", "Start Hotkey Window Binding"),
                    ("ok/ui/qt/debug/DebugTab.py", "UnregisterHotKey(hwnd, 1)", "Debug Hotkey Window Binding"),
                ]:
                    p = os.path.join(working_dir, mod_rel)
                    is_patched = os.path.isfile(p) and marker in open(p, "r", encoding="utf-8").read()
                    has_bak = os.path.isfile(p + ".orig")
                    print(f"  [{'x' if is_patched else ' '}] {name} ({mod_rel}) [backup: {has_bak}]")
            else:
                print("  [ ] Application core modules (working/ directory not installed)")

    def verify(self) -> bool:
        """Verify Python AST syntax and integrity of all target modules."""
        errors = 0
        checked = 0
        for site_packages, working_dir in self.trees:
            if site_packages:
                for sub in ["qframelesswindow/utils/win32_utils.py", "qframelesswindow/windows/window_effect.py", "qfluentwidgets/window/fluent_window.py"]:
                    p = os.path.join(site_packages, sub)
                    if os.path.isfile(p):
                        checked += 1
                        try:
                            ast.parse(open(p, "r", encoding="utf-8").read(), filename=p)
                        except SyntaxError as e:
                            print(f"  [FAIL] {sub}: {e}")
                            errors += 1
            if working_dir:
                for sub in ["ok/util/window.py", "ok/core/translation.py", "ok/util/explorer.py", "ok/util/process.py", "config.py",
                            "ok/device/capture_methods/bitblt_utils.py", "ok/ui/qt/start/StartCard.py", "ok/ui/qt/debug/DebugTab.py"]:
                    p = os.path.join(working_dir, sub)
                    if os.path.isfile(p):
                        checked += 1
                        try:
                            ast.parse(open(p, "r", encoding="utf-8").read(), filename=p)
                        except SyntaxError as e:
                            print(f"  [FAIL] {sub}: {e}")
                            errors += 1

        if checked == 0:
            print("  [WARN] 0 Python modules checked because application payload (working/ and python/) is not yet present.")
            return True
        elif errors == 0:
            print(f"  -> All {checked} target modules passed Python AST syntax validation cleanly.")
            return True
        else:
            print(f"  -> Verification failed with {errors} syntax error(s).")
            return False

    # ------------------ Internal Patch Implementations ------------------

    def _patch_qframelesswindow(self, site_packages: str):
        wu_path = os.path.join(site_packages, "qframelesswindow", "utils", "win32_utils.py")
        content = self._get_pristine_content(wu_path)
        if content:
            self._ensure_backup(wu_path)
            content = WINE_FUNC + content
            content = self._sub(content,
                'def isCompositionEnabled():\n    """ detect if dwm composition is enabled """\n    bResult = c_int(0)',
                'def isCompositionEnabled():\n    """ detect if dwm composition is enabled """\n    if is_wine():\n        return False\n    bResult = c_int(0)',
                "win32_utils isCompositionEnabled guard")
            content = self._sub(content,
                'def isGreaterEqualWin11():\n    """ determine if the windows version ≥ Win11 """\n    return isGreaterEqualWin10() and sys.getwindowsversion().build >= 22000',
                'def isGreaterEqualWin11():\n    """ determine if the windows version ≥ Win11 """\n    if is_wine():\n        return False\n    return isGreaterEqualWin10() and sys.getwindowsversion().build >= 22000',
                "win32_utils isGreaterEqualWin11 guard")
            if self._safe_write_python(wu_path, content):
                print("  -> Patched win32_utils.py")

        we_path = os.path.join(site_packages, "qframelesswindow", "windows", "window_effect.py")
        content = self._get_pristine_content(we_path)
        if content:
            self._ensure_backup(we_path)
            content = self._sub(content,
                "from ..utils.win32_utils import isGreaterEqualWin10, isGreaterEqualWin11, isCompositionEnabled",
                "from ..utils.win32_utils import isGreaterEqualWin10, isGreaterEqualWin11, isCompositionEnabled, is_wine",
                "window_effect is_wine import")
            content = self._sub(content,
                "    def addShadowEffect(self, hWnd):\n        if not isCompositionEnabled():\n            return",
                "    def addShadowEffect(self, hWnd):\n        if not isCompositionEnabled() or is_wine():\n            return",
                "window_effect addShadowEffect guard")
            content = self._sub(content,
                "    def setMicaEffect(self, hWnd, isDarkMode=False, isAlt=False):\n        if not isGreaterEqualWin11():",
                "    def setMicaEffect(self, hWnd, isDarkMode=False, isAlt=False):\n        if not isGreaterEqualWin11() or is_wine():",
                "window_effect setMicaEffect guard")
            content = self._sub(content,
                "    def enableBlurBehindWindow(self, hWnd):\n        blurBehind = DWM_BLURBEHIND(1, True, 0, False)",
                "    def enableBlurBehindWindow(self, hWnd):\n        if is_wine():\n            return\n        blurBehind = DWM_BLURBEHIND(1, True, 0, False)",
                "window_effect enableBlurBehindWindow guard")
            if self._safe_write_python(we_path, content):
                print("  -> Patched window_effect.py")

    def _patch_qfluentwidgets(self, site_packages: str):
        fw_path = os.path.join(site_packages, "qfluentwidgets", "window", "fluent_window.py")
        content = self._get_pristine_content(fw_path)
        if content:
            self._ensure_backup(fw_path)
            content = WINE_FUNC + content
            content = self._sub(content,
                "        # enable mica effect on win11\n        self.setMicaEffectEnabled(True)",
                "        # enable mica effect on win11 (unless on Wine)\n        if not is_wine():\n            self.setMicaEffectEnabled(True)\n        else:\n            self._isMicaEnabled = False\n            self.setBackgroundColor(self._normalBackgroundColor())",
                "fluent_window mica disable")
            content = self._sub(content,
                "        if sys.platform != 'win32' or sys.getwindowsversion().build < 22000:\n            return",
                "        if sys.platform != 'win32' or sys.getwindowsversion().build < 22000 or is_wine():\n            self._isMicaEnabled = False\n            self.setBackgroundColor(self._normalBackgroundColor())\n            return",
                "fluent_window setMicaEffectEnabled guard")
            if self._safe_write_python(fw_path, content):
                print("  -> Patched fluent_window.py")

    def _patch_app_modules(self, working_dir: str):
        # 1. window.py
        w_path = os.path.join(working_dir, "ok", "util", "window.py")
        content = self._get_pristine_content(w_path)
        if content:
            self._ensure_backup(w_path)
            content = WINE_FUNC + content
            content = self._sub(content,
                "def windows_graphics_available():\n",
                "def windows_graphics_available():\n    if is_wine():\n        return False\n",
                "window.py windows_graphics_available guard")
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
            content = self._sub(content, old_get_exe, new_get_exe, "window.py get_exe_by_hwnd query")
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
            content = self._sub(content, old_check, new_check, "window.py exe-name matching")
            if self._safe_write_python(w_path, content):
                print("  -> Patched ok/util/window.py")

        # 2. translation.py
        t_path = os.path.join(working_dir, "ok", "core", "translation.py")
        content = self._get_pristine_content(t_path)
        if content:
            self._ensure_backup(t_path)
            content = self._sub(content,
                "return gettext.translation('ok', dir_i18n, languages=fallback_list)",
                "return gettext.translation('ok', dir_i18n, languages=fallback_list, fallback=True)",
                "translation.py ok fallback")
            content = self._sub(content,
                "return gettext.translation('ocr', dir_i18n, languages=fallback_list)",
                "return gettext.translation('ocr', dir_i18n, languages=fallback_list, fallback=True)",
                "translation.py ocr fallback")
            if self._safe_write_python(t_path, content):
                print("  -> Patched ok/core/translation.py")

        # 3. explorer.py
        e_path = os.path.join(working_dir, "ok", "util", "explorer.py")
        content = self._get_pristine_content(e_path)
        if content:
            self._ensure_backup(e_path)
            content = WINE_FUNC + content
            content = self._sub(content,
                "    if _focus_existing_explorer_window(folder, item_name):\n        logger.info(f'Explorer focused existing window: folder={str(folder)!r}')\n        return True",
                "    if is_wine():\n        os.startfile(str(folder), 'explore')\n        logger.info('Explorer launch request completed (Wine)')\n        return True\n    if _focus_existing_explorer_window(folder, item_name):\n        logger.info(f'Explorer focused existing window: folder={str(folder)!r}')\n        return True",
                "explorer.py wine startfile")
            if self._safe_write_python(e_path, content):
                print("  -> Patched ok/util/explorer.py")

        # 4. process.py (nvidia-smi guard)
        p_path = os.path.join(working_dir, "ok", "util", "process.py")
        content = self._get_pristine_content(p_path)
        if content:
            self._ensure_backup(p_path)
            if "def is_wine():" not in content:
                content = WINE_FUNC + content
            content = self._sub(content,
                "def get_first_gpu_free_memory_mib():\n",
                "def get_first_gpu_free_memory_mib():\n    if is_wine():\n        return -1\n",
                "process.py gpu guard")
            if self._safe_write_python(p_path, content):
                print("  -> Patched ok/util/process.py")

        # 5. config.py
        c_path = os.path.join(working_dir, "config.py")
        content = self._get_pristine_content(c_path)
        if content:
            self._ensure_backup(c_path)
            old_calc = (
                "def calculate_pc_exe_path(running_path):\n"
                "    if running_path is None:\n"
                "        return _find_most_recently_run_pc_exe() or _find_pc_exe_from_registry()\n"
                "    game_exe_folder = Path(running_path).parents[3]\n"
                "    return str(game_exe_folder / \"Wuthering Waves.exe\")"
            )
            new_calc = (
                "def _find_steam_game_exe():\n"
                "    import string\n"
                "    from pathlib import Path\n"
                "    sub_candidates = (\n"
                "        ('common', 'Wuthering Waves', 'Wuthering Waves.exe'),\n"
                "        ('steamapps', 'common', 'Wuthering Waves', 'Wuthering Waves.exe'),\n"
                "        ('SteamLibrary', 'steamapps', 'common', 'Wuthering Waves', 'Wuthering Waves.exe'),\n"
                "        ('Program Files (x86)', 'Steam', 'steamapps', 'common', 'Wuthering Waves', 'Wuthering Waves.exe'),\n"
                "        ('Program Files', 'Steam', 'steamapps', 'common', 'Wuthering Waves', 'Wuthering Waves.exe'),\n"
                "        ('Wuthering Waves', 'Wuthering Waves.exe'),\n"
                "    )\n"
                "    for letter in string.ascii_uppercase:\n"
                "        drive = Path(f'{letter}:/')\n"
                "        if not drive.exists():\n"
                "            continue\n"
                "        for parts in sub_candidates:\n"
                "            cand = drive.joinpath(*parts)\n"
                "            try:\n"
                "                if cand.is_file():\n"
                "                    return str(cand)\n"
                "            except OSError:\n"
                "                continue\n"
                "    return None\n\n\n"
                "def calculate_pc_exe_path(running_path):\n"
                "    if running_path is None:\n"
                "        standalone = _find_most_recently_run_pc_exe() or _find_pc_exe_from_registry() or _find_steam_game_exe()\n"
                "        if standalone:\n"
                "            return standalone\n"
                "        return \"steam://rungameid/3513350\"\n"
                "    game_exe_folder = Path(running_path).parents[3]\n"
                "    return str(game_exe_folder / \"Wuthering Waves.exe\")"
            )
            content = self._sub(content, old_calc, new_calc, "config.py steam exe discovery")
            if self._safe_write_python(c_path, content):
                print("  -> Patched config.py")

        # 6. bitblt_utils.py
        bu_path = os.path.join(working_dir, "ok", "device", "capture_methods", "bitblt_utils.py")
        content = self._get_pristine_content(bu_path)
        if content:
            self._ensure_backup(bu_path)
            content = self._sub(content,
                "def capture_by_bitblt(context, hwnd, width, height, x, y, render_full_content):\n    if hwnd <= 0 or width <= 0 or height <= 0:\n        logger.error(f'capture_by_bitblt invalid params: hwnd={hwnd}, w={width}, h={height}')\n        return None",
                "def capture_by_bitblt(context, hwnd, width, height, x, y, render_full_content):\n    if hwnd <= 0 or width <= 0 or height <= 0:\n        return None\n    if not win32gui.IsWindow(hwnd):\n        clean_up_bitblt(context)\n        return None",
                "bitblt_utils.py hwnd validation")
            if self._safe_write_python(bu_path, content):
                print("  -> Patched ok/device/capture_methods/bitblt_utils.py")

        # 7. StartCard.py - bind hotkey to the widget's own window so
        #    RegisterHotKey/UnregisterHotKey stay symmetric (Wine leaks
        #    hotkeys registered to NULL after the widget is destroyed).
        sc_path = os.path.join(working_dir, "ok", "ui", "qt", "start", "StartCard.py")
        content = self._get_pristine_content(sc_path)
        if content:
            self._ensure_backup(sc_path)
            content = self._sub(content,
                "        windll.user32.UnregisterHotKey(None, 999)",
                "        hwnd = int(self.winId()) if hasattr(self, 'winId') else None\n        windll.user32.UnregisterHotKey(hwnd, 999)",
                "StartCard unregister hwnd")
            content = self._sub(content,
                "            if not windll.user32.RegisterHotKey(None, 999, 0, vk_map[hotkey]):",
                "            hwnd = int(self.winId()) if hasattr(self, 'winId') else None\n            if not windll.user32.RegisterHotKey(hwnd, 999, 0, vk_map[hotkey]):",
                "StartCard register hwnd")
            if self._safe_write_python(sc_path, content):
                print("  -> Patched ok/ui/qt/start/StartCard.py")

        # 8. DebugTab.py - same hotkey window binding, with symmetric
        #    unregister (the previous no-op replace left None here while
        #    registering with hwnd, leaking the hotkey).
        dt_path = os.path.join(working_dir, "ok", "ui", "qt", "debug", "DebugTab.py")
        content = self._get_pristine_content(dt_path)
        if content:
            self._ensure_backup(dt_path)
            content = self._sub(content,
                "        if not windll.user32.RegisterHotKey(None, 1, MOD_ALT | MOD_CONTROL, VK_D):",
                "        hwnd = int(self.winId()) if hasattr(self, 'winId') else None\n        if not windll.user32.RegisterHotKey(hwnd, 1, MOD_ALT | MOD_CONTROL, VK_D):",
                "DebugTab register hwnd 1")
            content = self._sub(content,
                "        if not windll.user32.RegisterHotKey(None, 2, MOD_ALT | MOD_CONTROL, VK_S):",
                "        hwnd = int(self.winId()) if hasattr(self, 'winId') else None\n        if not windll.user32.RegisterHotKey(hwnd, 2, MOD_ALT | MOD_CONTROL, VK_S):",
                "DebugTab register hwnd 2")
            content = self._sub(content,
                "        windll.user32.UnregisterHotKey(None, 1)\n        windll.user32.UnregisterHotKey(None, 2)",
                "        hwnd = int(self.winId()) if hasattr(self, 'winId') else None\n        windll.user32.UnregisterHotKey(hwnd, 1)\n        windll.user32.UnregisterHotKey(hwnd, 2)",
                "DebugTab unregister hwnd")
            if self._safe_write_python(dt_path, content):
                print("  -> Patched ok/ui/qt/debug/DebugTab.py")


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


def main():
    parser = argparse.ArgumentParser(description="Transactional Wine / Proton Compatibility Patcher for OK-WuWa")
    parser.add_argument("prefix", help="Path to Wine prefix or compatdata directory")
    parser.add_argument("--revert", "--undo", action="store_true", help="Revert all patches and restore pristine original files")
    parser.add_argument("--status", action="store_true", help="Show current patch status and backup existence")
    parser.add_argument("--verify", action="store_true", help="Validate syntax and integrity of all patched Python files")

    args = parser.parse_args()
    target = os.path.abspath(args.prefix)

    pfx_path = resolve_prefix(target)
    if not pfx_path or not os.path.isdir(pfx_path):
        print(f"Error: Could not determine Wine prefix from '{target}'")
        sys.exit(1)

    engine = PatchEngine(pfx_path)

    if args.revert:
        engine.revert_patches()
    elif args.status:
        engine.get_status()
    elif args.verify:
        engine.verify()
    else:
        success = engine.apply_patches()
        if not success:
            sys.exit(1)


if __name__ == "__main__":
    main()
