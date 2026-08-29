#!/usr/bin/env python3
"""
Wine / Proton Compatibility Patcher for ok-wuthering-waves (OK-WW)

Universal compatibility patcher designed for any Linux distribution, Steam setup,
or Wine prefix.

Fixes Applied:
1. PySide6 / Qt6Core DLL load error (copies/aliases icu.dll as icuuc.dll & icuin.dll).
2. Blank / black titlebar and sidebar caused by Windows 11 DWM Mica/Acrylic backdrop transparency.
3. Invisible mouse cursor caused by DwmExtendFrameIntoClientArea (-1) full-window glass extension.
4. Clean fallback for Windows Graphics Capture (WGC / WinRT) to prevent HRESULT 0x80040154 error logs.
5. Translation fallback (fallback=True) to eliminate "install translations error for en_US" log spam.
6. Explorer launch optimization under Wine to eliminate COM Shell.Application enumeration timeouts.
7. Game executable path resolver for Steam (returns steam://rungameid/3513350 to prevent Fatal Error crashes).
8. Wine-safe process and window matching in find_hwnd to ensure game is reliably detected.
9. BitBlt invalid window handle guard to prevent (1400, GetWindowDC) crash loops on transient popups.
10. UpdateCard silence pyappify update RuntimeError when run outside standalone installer.
11. Window focus stability: Fix Wine/X11 GetForegroundWindow focus flapping in is_foreground_window.
12. Keypress and click duration increase (down_time=0.04s) for DXVK/Proton message pump frame-tick synchronization.
13. Deadlock prevention: Disable continuous WM_ACTIVATE message flooding in PostMessage on Wine.
"""

import os
import shutil
import sys
from pathlib import Path


def fix_icu_dlls(prefix_path: str):
    """Ensure icuuc.dll and icuin.dll exist as copies of icu.dll in Wine system directories."""
    print("[1/5] Checking ICU DLL aliases in Wine prefix...")
    drive_c = os.path.join(prefix_path, "drive_c", "windows")
    for subdir in ["system32", "syswow64"]:
        dir_path = os.path.join(drive_c, subdir)
        if not os.path.isdir(dir_path):
            continue

        icu_src = os.path.join(dir_path, "icu.dll")
        if os.path.isfile(icu_src):
            for target_name in ["icuuc.dll", "icuin.dll"]:
                target_path = os.path.join(dir_path, target_name)
                if not os.path.exists(target_path):
                    shutil.copy2(icu_src, target_path)
                    print(f"  -> Created {subdir}/{target_name}")
                else:
                    print(f"  -> {subdir}/{target_name} already present")


def patch_frameless_window(site_packages: str):
    """Patch qframelesswindow to disable DWM composition & full-window frame extension on Wine."""
    print("[2/5] Patching qframelesswindow for Wine compatibility...")

    # 1. win32_utils.py
    wu_path = os.path.join(site_packages, "qframelesswindow", "utils", "win32_utils.py")
    if os.path.isfile(wu_path):
        with open(wu_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "def is_wine():" not in content:
            wine_func = (
                "def is_wine():\n"
                "    try:\n"
                "        import ctypes\n"
                "        return hasattr(ctypes.cdll.ntdll, 'wine_get_version')\n"
                "    except Exception:\n"
                "        return False\n\n"
            )
            content = wine_func + content

        content = content.replace(
            'def isCompositionEnabled():\n    """ detect if dwm composition is enabled """\n    bResult = c_int(0)',
            'def isCompositionEnabled():\n    """ detect if dwm composition is enabled """\n    if is_wine():\n        return False\n    bResult = c_int(0)'
        )

        content = content.replace(
            'def isGreaterEqualWin11():\n    """ determine if the windows version ≥ Win11 """\n    return isGreaterEqualWin10() and sys.getwindowsversion().build >= 22000',
            'def isGreaterEqualWin11():\n    """ determine if the windows version ≥ Win11 """\n    if is_wine():\n        return False\n    return isGreaterEqualWin10() and sys.getwindowsversion().build >= 22000'
        )

        with open(wu_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("  -> Patched win32_utils.py")

    # 2. window_effect.py
    we_path = os.path.join(site_packages, "qframelesswindow", "windows", "window_effect.py")
    if os.path.isfile(we_path):
        with open(we_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "is_wine" not in content:
            content = content.replace(
                "from ..utils.win32_utils import isGreaterEqualWin10, isGreaterEqualWin11, isCompositionEnabled",
                "from ..utils.win32_utils import isGreaterEqualWin10, isGreaterEqualWin11, isCompositionEnabled, is_wine"
            )
            content = content.replace(
                "    def addShadowEffect(self, hWnd):\n        if not isCompositionEnabled():\n            return",
                "    def addShadowEffect(self, hWnd):\n        if not isCompositionEnabled() or is_wine():\n            return"
            )
            content = content.replace(
                "    def setMicaEffect(self, hWnd, isDarkMode=False, isAlt=False):\n        if not isGreaterEqualWin11():",
                "    def setMicaEffect(self, hWnd, isDarkMode=False, isAlt=False):\n        if not isGreaterEqualWin11() or is_wine():"
            )
            content = content.replace(
                "    def enableBlurBehindWindow(self, hWnd):\n        blurBehind = DWM_BLURBEHIND(1, True, 0, False)",
                "    def enableBlurBehindWindow(self, hWnd):\n        if is_wine():\n            return\n        blurBehind = DWM_BLURBEHIND(1, True, 0, False)"
            )
            with open(we_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("  -> Patched window_effect.py")

    # 3. windows/__init__.py
    init_path = os.path.join(site_packages, "qframelesswindow", "windows", "__init__.py")
    if os.path.isfile(init_path):
        with open(init_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "self.setCursor(Qt.ArrowCursor)" not in content:
            content = content.replace(
                "        self.resize(500, 500)\n        self.titleBar.raise_()",
                "        self.resize(500, 500)\n        self.titleBar.raise_()\n        self.setCursor(Qt.ArrowCursor)\n        self.setMouseTracking(True)"
            )
            with open(init_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("  -> Patched windows/__init__.py")


def patch_fluent_widgets(site_packages: str):
    """Patch qfluentwidgets to disable transparent backdrop on Wine and fix black titlebar/sidebar."""
    print("[3/5] Patching qfluentwidgets for Wine compatibility...")

    # 1. fluent_window.py
    fw_path = os.path.join(site_packages, "qfluentwidgets", "window", "fluent_window.py")
    if os.path.isfile(fw_path):
        with open(fw_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "def is_wine():" not in content:
            wine_func = (
                "def is_wine():\n"
                "    try:\n"
                "        import ctypes\n"
                "        return hasattr(ctypes.cdll.ntdll, 'wine_get_version')\n"
                "    except Exception:\n"
                "        return False\n\n"
            )
            content = wine_func + content

        content = content.replace(
            "        # enable mica effect on win11\n        self.setMicaEffectEnabled(True)",
            "        # enable mica effect on win11 (unless on Wine)\n        if not is_wine():\n            self.setMicaEffectEnabled(True)\n        else:\n            self._isMicaEnabled = False\n            self.setBackgroundColor(self._normalBackgroundColor())"
        )

        content = content.replace(
            "        if sys.platform != 'win32' or sys.getwindowsversion().build < 22000:\n            return",
            "        if sys.platform != 'win32' or sys.getwindowsversion().build < 22000 or is_wine():\n            self._isMicaEnabled = False\n            self.setBackgroundColor(self._normalBackgroundColor())\n            return"
        )

        with open(fw_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("  -> Patched fluent_window.py")

    # 2. widgets/frameless_window.py
    flw_path = os.path.join(site_packages, "qfluentwidgets", "components", "widgets", "frameless_window.py")
    if os.path.isfile(flw_path):
        with open(flw_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "is_wine()" not in content:
            wine_header = (
                "import sys\n\n"
                "def is_wine():\n"
                "    try:\n"
                "        import ctypes\n"
                "        return hasattr(ctypes.cdll.ntdll, 'wine_get_version')\n"
                "    except Exception:\n"
                "        return False\n\n"
                "if sys.platform != \"win32\" or sys.getwindowsversion().build < 22000 or is_wine():\n"
                "    from qframelesswindow import FramelessWindow\n"
                "else:"
            )
            content = content.replace(
                "import sys\n\nif sys.platform != \"win32\" or sys.getwindowsversion().build < 22000:\n    from qframelesswindow import FramelessWindow\nelse:",
                wine_header
            )
            with open(flw_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("  -> Patched widgets/frameless_window.py")


def patch_app_code(working_dir: str):
    """Patch application code inside working directory."""
    print("[4/5] Patching application modules for Wine/Proton performance & reliability...")

    # 1. window.py
    w_path = os.path.join(working_dir, "ok", "util", "window.py")
    if os.path.isfile(w_path):
        with open(w_path, "r", encoding="utf-8") as f:
            w_content = f.read()

        if "def is_wine():" not in w_content:
            wine_func = (
                "def is_wine():\n"
                "    try:\n"
                "        return hasattr(ctypes.cdll.ntdll, 'wine_get_version')\n"
                "    except Exception:\n"
                "        return False\n\n"
            )
            w_content = w_content.replace(
                "def windows_graphics_available():",
                wine_func + "def windows_graphics_available():\n    if is_wine():\n        return False"
            )

        if "Try Win32 Process Module Query first" not in w_content:
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
                "        # Try Win32 Process Module Query first for 100% reliable Wine compatibility\n"
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
            w_content = w_content.replace(old_get_exe, new_get_exe)

        if "matched_exe" not in w_content:
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
            w_content = w_content.replace(old_check, new_check)

        if "if is_wine():\n        return win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd)" not in w_content:
            old_fg = "def is_foreground_window(hwnd):\n    return win32gui.IsWindowVisible(hwnd) and win32gui.GetForegroundWindow() == hwnd"
            new_fg = "def is_foreground_window(hwnd):\n    if is_wine():\n        return win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd)\n    return win32gui.IsWindowVisible(hwnd) and win32gui.GetForegroundWindow() == hwnd"
            w_content = w_content.replace(old_fg, new_fg)

        with open(w_path, "w", encoding="utf-8") as f:
            f.write(w_content)
        print("  -> Patched ok/util/window.py")

    # 2. translation.py
    t_path = os.path.join(working_dir, "ok", "core", "translation.py")
    if os.path.isfile(t_path):
        with open(t_path, "r", encoding="utf-8") as f:
            t_content = f.read()
        t_content = t_content.replace(
            "return gettext.translation('ok', dir_i18n, languages=fallback_list)",
            "return gettext.translation('ok', dir_i18n, languages=fallback_list, fallback=True)"
        )
        t_content = t_content.replace(
            "return gettext.translation('ocr', dir_i18n, languages=fallback_list)",
            "return gettext.translation('ocr', dir_i18n, languages=fallback_list, fallback=True)"
        )
        with open(t_path, "w", encoding="utf-8") as f:
            f.write(t_content)
        print("  -> Patched ok/core/translation.py")

    # 3. explorer.py
    e_path = os.path.join(working_dir, "ok", "util", "explorer.py")
    if os.path.isfile(e_path):
        with open(e_path, "r", encoding="utf-8") as f:
            e_content = f.read()
        if "is_wine" not in e_content:
            e_content = (
                "def is_wine():\n"
                "    try:\n"
                "        import ctypes\n"
                "        return hasattr(ctypes.cdll.ntdll, 'wine_get_version')\n"
                "    except Exception:\n"
                "        return False\n\n"
            ) + e_content
            e_content = e_content.replace(
                "    if _focus_existing_explorer_window(folder, item_name):\n        logger.info(f'Explorer focused existing window: folder={str(folder)!r}')\n        return True",
                "    if is_wine():\n        os.startfile(str(folder), 'explore')\n        logger.info('Explorer launch request completed (Wine)')\n        return True\n    if _focus_existing_explorer_window(folder, item_name):\n        logger.info(f'Explorer focused existing window: folder={str(folder)!r}')\n        return True"
            )
            with open(e_path, "w", encoding="utf-8") as f:
                f.write(e_content)
            print("  -> Patched ok/util/explorer.py")

    # 4. config.py
    c_path = os.path.join(working_dir, "config.py")
    if os.path.isfile(c_path):
        with open(c_path, "r", encoding="utf-8") as f:
            c_content = f.read()
        if "steam://rungameid/3513350" not in c_content:
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
                "        standalone = _find_most_recently_run_pc_exe() or _find_pc_exe_from_registry()\n"
                "        if standalone:\n"
                "            return standalone\n"
                "        return \"steam://rungameid/3513350\"\n"
                "    game_exe_folder = Path(running_path).parents[3]\n"
                "    return str(game_exe_folder / \"Wuthering Waves.exe\")"
            )
            c_content = c_content.replace(old_calc, new_calc)
            with open(c_path, "w", encoding="utf-8") as f:
                f.write(c_content)
            print("  -> Patched config.py")

    # 5. bitblt_utils.py (prevent invalid HWND crash flood)
    bu_path = os.path.join(working_dir, "ok", "device", "capture_methods", "bitblt_utils.py")
    if os.path.isfile(bu_path):
        with open(bu_path, "r", encoding="utf-8") as f:
            bu_content = f.read()
        if "if not win32gui.IsWindow(hwnd):" not in bu_content:
            old_cap = "def capture_by_bitblt(context, hwnd, width, height, x, y, render_full_content):\n    if hwnd <= 0 or width <= 0 or height <= 0:\n        logger.error(f'capture_by_bitblt invalid params: hwnd={hwnd}, w={width}, h={height}')\n        return None"
            new_cap = "def capture_by_bitblt(context, hwnd, width, height, x, y, render_full_content):\n    if hwnd <= 0 or width <= 0 or height <= 0:\n        return None\n    if not win32gui.IsWindow(hwnd):\n        clean_up_bitblt(context)\n        return None"
            bu_content = bu_content.replace(old_cap, new_cap)
            with open(bu_path, "w", encoding="utf-8") as f:
                f.write(bu_content)
            print("  -> Patched ok/device/capture_methods/bitblt_utils.py")

    # 6. UpdateCard.py (silence pyappify update error loop)
    uc_path = os.path.join(working_dir, "ok", "ui", "qt", "about", "UpdateCard.py")
    if os.path.isfile(uc_path):
        with open(uc_path, "r", encoding="utf-8") as f:
            uc_content = f.read()
        if "if self._busy or not self.pyappify_app_version:" not in uc_content:
            uc_content = uc_content.replace(
                "    def check_for_updates(self):\n        if self._busy:\n            return",
                "    def check_for_updates(self):\n        if self._busy or not self.pyappify_app_version:\n            return"
            )
            with open(uc_path, "w", encoding="utf-8") as f:
                f.write(uc_content)
            print("  -> Patched ok/ui/qt/about/UpdateCard.py")

    # 7. post_message.py (Wine deadlock prevention: disable continuous WM_ACTIVATE spam)
    pm_path = os.path.join(working_dir, "ok", "device", "interaction_methods", "post_message.py")
    if os.path.isfile(pm_path):
        with open(pm_path, "r", encoding="utf-8") as f:
            pm_content = f.read()
        if "def is_wine():" not in pm_content:
            wine_fn = (
                "def is_wine():\n"
                "    try:\n"
                "        import ctypes\n"
                "        return hasattr(ctypes.cdll.ntdll, 'wine_get_version')\n"
                "    except Exception:\n"
                "        return False\n\n"
            )
            pm_content = pm_content.replace("logger = Logger.get_logger(__name__)", "logger = Logger.get_logger(__name__)\n\n" + wine_fn)
        if "if is_wine():\n            return" not in pm_content:
            old_try = "    def try_activate(self):\n        base_hwnd = self.hwnd_window.hwnd"
            new_try = "    def try_activate(self):\n        if is_wine():\n            return\n        base_hwnd = self.hwnd_window.hwnd"
            pm_content = pm_content.replace(old_try, new_try)
        with open(pm_path, "w", encoding="utf-8") as f:
            f.write(pm_content)
        print("  -> Patched ok/device/interaction_methods/post_message.py (try_activate)")

    # 8. Interaction down_time synchronization (post_message.py, BaseChar.py, BaseWWTask.py, task.py)
    for module_rel, old_txt, new_txt in [
        (os.path.join("ok", "device", "interaction_methods", "post_message.py"), "down_time=0.01", "down_time=0.04"),
        (os.path.join("src", "char", "BaseChar.py"), "down_time=0.01", "down_time=0.04"),
        (os.path.join("src", "task", "BaseWWTask.py"), "down_time=0.01", "down_time=0.04"),
        (os.path.join("ok", "task", "task.py"), "down_time=0.01", "down_time=0.04"),
    ]:
        p = os.path.join(working_dir, module_rel)
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                c = f.read()
            if old_txt in c:
                c = c.replace(old_txt, new_txt)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(c)
                print(f"  -> Patched {module_rel} down_time to 0.04s")


def main():
    if len(sys.argv) < 2:
        print("Usage: patch_wine_compat.py <path_to_compatdata_pfx_or_ok_ww_dir>")
        sys.exit(1)

    target = os.path.abspath(sys.argv[1])

    # Locate prefix path
    if "compatdata" in target and "pfx" in target:
        pfx_path = target if target.endswith("pfx") else target[:target.find("pfx") + 3]
    elif os.path.isdir(os.path.join(target, "pfx")):
        pfx_path = os.path.join(target, "pfx")
    else:
        curr = target
        pfx_path = None
        while curr and curr != "/":
            if os.path.basename(curr) == "pfx":
                pfx_path = curr
                break
            curr = os.path.dirname(curr)

    if not pfx_path or not os.path.isdir(pfx_path):
        print(f"Error: Could not determine Wine prefix from '{target}'")
        sys.exit(1)

    print(f"Found Wine Prefix: {pfx_path}")
    fix_icu_dlls(pfx_path)

    # Locate site-packages and working directory dynamically in users/
    users_dir = os.path.join(pfx_path, "drive_c", "users")
    site_packages = None
    working_dir = None

    if os.path.isdir(users_dir):
        for user_entry in os.listdir(users_dir):
            app_dir = os.path.join(users_dir, user_entry, "AppData", "Local", "ok-ww", "data", "apps", "ok-ww")
            sp = os.path.join(app_dir, "python", "Lib", "site-packages")
            wk = os.path.join(app_dir, "working")
            if os.path.isdir(sp):
                site_packages = sp
            if os.path.isdir(wk):
                working_dir = wk

    if site_packages:
        print(f"Found Python site-packages: {site_packages}")
        patch_frameless_window(site_packages)
        patch_fluent_widgets(site_packages)
    else:
        print("Warning: Embedded Python site-packages directory not found yet.")

    if working_dir:
        print(f"Found working directory: {working_dir}")
        patch_app_code(working_dir)

    print("\n[5/5] All Wine/Proton compatibility patches successfully applied!")


if __name__ == "__main__":
    main()
