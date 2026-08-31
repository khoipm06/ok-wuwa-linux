# OK-WuWa on Proton

Run [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) on Linux under Steam Proton, Flatpak Steam, and Wine.


## Prerequisites

- Wuthering Waves installed and run once in Steam.
- Python 3 on your host system.

## Quick Start

```bash
git clone https://github.com/khoipm06/ok-wuwa-proton.git
cd ok-wuwa-proton
./setup.sh
```

The script locates your Steam libraries, applies Wine compatibility fixes to the prefix, and installs the desktop launcher.

## Usage

### Run OK-WuWa Directly

Launch it from your application menu or terminal:

```bash
ok-wuwa
```

From here you can:
- Start OK-WuWa, then click **Start** in the UI to launch Wuthering Waves. (Or enable the auto-start option in the settings.)
- Start Wuthering Waves in Steam first, then launch OK-WuWa.

To bypass the Tauri launcher and run the Python app directly (no WebView2 involved):

```bash
ok-wuwa --direct
```

### Optional: 1-Click Steam Integration

To start OK-WuWa automatically whenever you launch Wuthering Waves from Steam:

1. Open Steam, right-click **Wuthering Waves**, and select **Properties**.
2. Set **Launch Options** to:
   ```bash
   ~/.local/share/ok-wuwa/steam-wrapper.sh %command%
   ```

## Patch Management

The patcher includes built-in verification and rollback commands:

```bash
# Check status of applied fixes and backups
python3 patch_wine_compat.py /path/to/prefix --status

# Verify syntax across all patched files
python3 patch_wine_compat.py /path/to/prefix --verify

# Revert all changes and restore original files
python3 patch_wine_compat.py /path/to/prefix --revert
```

## Structure

- `setup.sh`: Automated setup, git auto-updater, and prefix patcher.
- `common.sh`: Shared routines used by every launcher and wrapper (Steam library/prefix/Proton discovery, WebView2 detection, render-fix, cursor watcher, compat patches).
- `ok-wuwa`: Standalone desktop launcher for `ok-ww.exe`.
- `steam-wrapper.sh`: Companion wrapper for Steam launch options; applies the same fixes as `ok-wuwa`.
- `patch_wine_compat.py`: Safe, reversible Wine patch engine with AST validation.
- `cursor_visible.py`: Host-side watcher that restores the mouse cursor over the ok-ww window on KWin/XWayland.
- `webview2_render_fix.py`: In-prefix helper that kicks WebView2/Chromium into presenting its first frame on Wine.
