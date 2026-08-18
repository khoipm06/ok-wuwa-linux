#!/usr/bin/env python3
"""
Wine / Proton Compatibility Patcher for ok-wuthering-waves (OK-WW)

Universal compatibility patcher designed for any Linux distribution, Steam setup,
or Wine prefix.

Fixes Applied:
1. PySide6 / Qt6Core DLL load error (copies/aliases icu.dll as icuuc.dll & icuin.dll).
"""

import os
import shutil
import sys
from pathlib import Path


def fix_icu_dlls(prefix_path: str):
    """Ensure icuuc.dll and icuin.dll exist as copies of icu.dll in Wine system directories."""
    print("[1/2] Checking ICU DLL aliases in Wine prefix...")
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

    print("\n[2/2] Wine/Proton compatibility patches successfully applied!")


if __name__ == "__main__":
    main()
