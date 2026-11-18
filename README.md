# OK-WuWa on Linux

Run [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) seamlessly on Linux & Steam Deck under Steam Proton (both Flatpak Steam and native Steam) with **zero game-prefix pollution** and **any-order container attachment**.

## Features

- **Zero-Pollution Storage**: Installs OK-WW and its standalone Python 3.12 runtime under `~/.local/share/ok-wuwa/app` instead of modifying Wuthering Waves's `compatdata/3513350/pfx`. Recreating your Proton prefix or switching Proton builds never wipes OK-WW or your task configs.
- **Launch in Any Order (No Launch Options Required)**:
  - **Game already running**: `ok-wuwa` automatically detects `Client-Win64-Shipping.exe` and enters the game's live pressure-vessel container (`flatpak enter` on Flatpak Steam, `nsenter` on native Steam), sharing the exact same `/tmp` (`wineserver`) and `/dev/shm` (`fsync`).
  - **OK-WuWa started first**: Clicking **Start Wuthering Waves** inside OK-WW cleanly closes the temporary pre-game container, launches the game safely through Steam (`steam://rungameid/3513350`), and automatically re-attaches inside the game's container once it starts.
  - **Optional 1-Click Companion**: `steam-wrapper.sh %command%` starts OK-WuWa automatically whenever you launch Wuthering Waves from Steam.
- **Exact Proton Matching**: Reads `compatdata/<appid>/config_info` to select the exact Proton runner (`DW-Proton`, `Proton-CachyOS`, `GE-Proton`, `Proton Experimental`, etc.) used by the game, preventing `wineserver` protocol mismatches.
- **Version-Agnostic Win32 Runtime Shim (Zero Upstream File Edits)**: Instead of brittle text-replacement patches on upstream `.py` files (which break whenever upstream renames or refactors modules), `patch_wine_compat.py` installs an in-memory Win32/Python runtime shim (`sitecustomize.py`) inside the bundled Python environment. The entire OK-WW `working/` checkout stays **100% unmodified upstream**, so future updates (`v3.9`, `v4.0`, new characters, new tasks, UI refactors) work out-of-the-box without needing manual re-porting.

## Prerequisites

- **Wuthering Waves** installed in Steam (Flatpak or native) and launched at least once.
- `bash`, `git`, `curl`, and `python3` on your host Linux system.

## Quick Start

```bash
git clone https://github.com/khoipm06/ok-wuwa-linux.git
cd ok-wuwa-linux
./setup.sh
```

`setup.sh` discovers your Steam library and Proton runner, configures Flatpak Steam access to `~/.local/share/ok-wuwa` (if applicable), bootstraps OK-WW into `~/.local/share/ok-wuwa/app`, applies Wine/Proton compatibility patches, and installs the `ok-wuwa` CLI and desktop entry.

## Usage

### Run Anytime (Desktop Menu or CLI)

```bash
ok-wuwa
```

- Start Wuthering Waves in Steam first, then run `ok-wuwa` — it joins the running game container and connects immediately.
- Or run `ok-wuwa` first, configure your tasks, and click **Start Wuthering Waves** — it launches the game via Steam and transitions into the game's container automatically.

### Update OK-WW

Update from inside OK-WW (**About → Update**) or from your terminal:

```bash
ok-wuwa --update
```

### Optional: 1-Click Steam Launch Option

To launch OK-WuWa automatically every time Wuthering Waves starts from Steam:

1. In Steam, right-click **Wuthering Waves → Properties**.
2. Set **Launch Options** to:
   ```bash
   ~/.local/share/ok-wuwa/steam-wrapper.sh %command%
   ```

## Runtime Compatibility Layer

`patch_wine_compat.py` keeps `working/` 100% untouched on disk and hooks stable OS / Win32 / Python API boundaries in memory whenever `python.exe` starts under Wine (`ntdll.wine_get_version`):

| Boundary / Hook | Fix Applied |
| --- | --- |
| `sys.getwindowsversion` / `platform.version` | Reports Windows 10 `10.0.19045`, automatically disabling unimplemented Windows 11 DWM Mica/Acrylic glass backdrops and broken WinRT `Windows.Graphics.Capture` across any current or future UI toolkit. |
| `user32.RegisterHotKey` & `PeekMessageW` | Virtualizes background-thread Win32 hotkey loops via `GetAsyncKeyState` so Wine never creates a deadlocking X11 thread input queue, keeping `F9–F12` and `Ctrl+Alt+D/S` hotkeys working regardless of which UI module registers them. |
| `win32gui.PostMessage` | Suppresses Wine focus-stealing `WM_ACTIVATE` spam and enforces a `>= 40ms` hold between `DOWN` and `UP` messages so DXVK/UE4 frame ticks never drop fast taps. |
| `gettext.translation` | Retries missing `.mo` locale lookups with `fallback=True` so locales like `en_US` never raise `FileNotFoundError`. |
| `os.startfile` & `subprocess` | Coordinates anti-cheat-safe pre-game `steam://rungameid/3513350` container handoff and silences missing Windows `nvidia-smi.exe` probes. |
| `sys.meta_path` non-invasive import hooks | Enables background `BitBlt` capture without requiring foreground focus (`OKWW_REQUIRE_FOREGROUND=1` to opt out), guards `BitBlt` against closed `HWND`s, and bypasses unimplemented `Shell.Application` COM loops. |

```bash
# Inspect runtime layer status
ok-wuwa --status

# Verify runtime shim AST & installation
ok-wuwa --verify

# Remove runtime shim completely
ok-wuwa --revert
```

## Repository Structure

- `setup.sh` — Automated zero-pollution installer and XDG desktop integration.
- `common.sh` — Shared Steam library, `config_info` Proton runner, Btrfs mount alias, and container-join routines.
- `ok-wuwa` — Universal launcher, container handoff supervisor, and CLI updater.
- `steam-wrapper.sh` — Optional companion wrapper for Steam Launch Options.
- `patch_wine_compat.py` — Version-agnostic in-memory Win32/Python runtime shim (`sitecustomize.py`) with zero edits to upstream OK-WW files.

## License

[MIT](LICENSE)
