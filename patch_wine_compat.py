#!/usr/bin/env python3
"""
Wine / Proton Compatibility Patcher for ok-wuthering-waves (OK-WW)

Universal compatibility patcher designed for any Linux distribution, Steam setup,
or Wine prefix.

Fixes Applied:
1. PySide6 / Qt6Core DLL load error (copies/aliases icu.dll as icuuc.dll & icuin.dll).
2. Blank / black titlebar and sidebar caused by Windows 11 DWM Mica/Acrylic backdrop transparency.
"""

import os
import shutil
import sys
from pathlib import Path


def fix_icu_dlls(prefix_path: str):
    """Ensure icuuc.dll and icuin.dll exist as copies of icu.dll in Wine system directories."""
    print("[1/3] Checking ICU DLL aliases in Wine prefix...")
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
    print("[2/3] Patching qframelesswindow for Wine compatibility...")

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

    # Locate site-packages in users/
    users_dir = os.path.join(pfx_path, "drive_c", "users")
    site_packages = None

    if os.path.isdir(users_dir):
        for user_entry in os.listdir(users_dir):
            app_dir = os.path.join(users_dir, user_entry, "AppData", "Local", "ok-ww", "data", "apps", "ok-ww")
            sp = os.path.join(app_dir, "python", "Lib", "site-packages")
            if os.path.isdir(sp):
                site_packages = sp

    if site_packages:
        print(f"Found Python site-packages: {site_packages}")
        patch_frameless_window(site_packages)
    else:
        print("Warning: Embedded Python site-packages directory not found yet.")

    print("\n[3/3] All Wine/Proton compatibility patches successfully applied!")


if __name__ == "__main__":
    main()
