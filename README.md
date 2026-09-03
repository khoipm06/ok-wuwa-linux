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
- Start OK-WuWa, then click **Start** in the UI to launch Wuthering Waves through Steam (needs the Steam client running). (Or enable the auto-start option in the settings.)
- Start Wuthering Waves in Steam first, then launch OK-WuWa; it attaches to the running game.

The app runs nested inside the Steam flatpak sandbox so it shares the game's
Wine server (window capture/attach) and the Steam client pipe (`steam://`
launch). The Tauri launcher shell (WebView2) cannot survive that nesting, so
the Python app is the default entry point. To run the Tauri shell on the host
instead (launcher UX only, no attach/Start):

```bash
ok-wuwa --launcher
```

### Optional: 1-Click Steam Integration

To start OK-WuWa automatically whenever you launch Wuthering Waves from Steam:

1. Open Steam, right-click **Wuthering Waves**, and select **Properties**.
2. Set **Launch Options** to:
   ```bash
   ~/.local/share/ok-wuwa/steam-wrapper.sh %command%
   ```

## Patch Management

The patcher is quilt-style and idempotent: every apply rebuilds each file
from pristine content fetched from upstream (`ok-oldking/ok-ww-update` at the
installed version tag, or the matching PyPI wheel for GUI packages), so
re-running never stacks edits and ok-ww self-updates are handled by the next
apply. A `~/.cache/ok-wuwa/pristine/` cache makes re-runs offline-friendly,
and `.orig` snapshots next to each file are the last-resort fallback.

```bash
# Check status of applied fixes and backups
python3 patch_wine_compat.py /path/to/prefix --status

# Verify syntax across all patched files
python3 patch_wine_compat.py /path/to/prefix --verify

# Restore every patched file to pristine upstream content
python3 patch_wine_compat.py /path/to/prefix --revert
```

## Structure

- `setup.sh`: Automated setup, git auto-updater, and prefix patcher.
- `common.sh`: Shared routines used by every launcher and wrapper (Steam library/prefix/Proton discovery, nested-flatpak launch, WebView2 detection, cursor watcher, compat patches).
- `ok-wuwa`: Standalone desktop launcher; runs the Python app nested in the Steam flatpak so it shares the game's Wine server and Steam pipe.
- `steam-wrapper.sh`: Companion wrapper for Steam launch options; starts the Python app alongside the game inside the same container context.
- `patch_wine_compat.py`: Quilt-style idempotent patch engine sourcing pristine content from upstream.
- `cursor_visible.py`: Host-side watcher that restores the mouse cursor over the ok-ww window on KWin/XWayland.
- `webview2_render_fix.py`: In-prefix helper that kicks WebView2/Chromium into presenting its first frame on Wine.
