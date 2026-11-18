# OK-WuWa on Linux

Run [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) seamlessly on Linux & Steam Deck under Steam Proton (both Flatpak Steam and native Steam) with **zero game-prefix pollution** and **any-order container attachment**.

## Features

- **Zero-Pollution Storage**: Installs OK-WW and its standalone Python 3.12 runtime under `~/.local/share/ok-wuwa/app` instead of modifying Wuthering Waves's `compatdata/3513350/pfx`. Recreating your Proton prefix or switching Proton builds never wipes OK-WW or your task configs.
- **Launch in Any Order (No Launch Options Required)**:
  - **Game already running**: `ok-wuwa` automatically detects `Client-Win64-Shipping.exe` and enters the game's live pressure-vessel container (`flatpak enter` on Flatpak Steam, `nsenter` on native Steam), sharing the exact same `/tmp` (`wineserver`) and `/dev/shm` (`fsync`).
  - **OK-WuWa started first**: Clicking **Start Wuthering Waves** inside OK-WW cleanly closes the temporary pre-game container, launches the game safely through Steam (`steam://rungameid/3513350`), and automatically re-attaches inside the game's container once it starts.
  - **Optional 1-Click Companion**: `steam-wrapper.sh %command%` starts OK-WuWa automatically whenever you launch Wuthering Waves from Steam.
- **Exact Proton Matching**: Reads `compatdata/<appid>/config_info` to select the exact Proton runner (`DW-Proton`, `Proton-CachyOS`, `GE-Proton`, `Proton Experimental`, etc.) used by the game, preventing `wineserver` protocol mismatches.
- **Self-Healing Idempotent Patcher**: Rebuilds patched modules from the local bare git repository (`~/.local/share/ok-wuwa/app/data/apps/ok-ww/repo`), validates AST syntax, and installs a `sitecustomize.py` hook so in-app updates via the **About** tab automatically re-apply Wine compatibility fixes on restart.

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

## Patch Management

```bash
# Inspect patch status
ok-wuwa --status

# Validate Python AST across all patched modules
ok-wuwa --verify

# Restore all modules to pristine upstream source
ok-wuwa --revert
```

You can also invoke `patch_wine_compat.py` directly (`python3 patch_wine_compat.py --status`, `--offline`, `--revert`).

## What Gets Patched (and Why)

Every patch applied by `patch_wine_compat.py` is scoped behind `is_wine()` (`ntdll.wine_get_version`):

| Target Module | Fix Applied |
| --- | --- |
| `ok/ui/qt/kit/theme.py` | Disables unimplemented Windows 11 DWM Mica/Acrylic glass backdrops on Wine (`build >= 22000`) for crisp solid rendering. |
| `ok/ui/qt/shell/run_bar.py` | Replaces background-thread `PeekMessageW` + `RegisterHotKey` (which deadlocks Wine's X11 thread input queue) with a GUI-thread `QTimer` + `GetAsyncKeyState` poller so `F9–F12` hotkeys work safely. |
| `ok/ui/qt/debug/diagnosis_page.py` | Same deadlock-free `GetAsyncKeyState` replacement for `Ctrl+Alt+D` / `Ctrl+Alt+S` diagnostic hotkeys. |
| `ok/util/window.py` | Skips unavailable WinRT `Windows.Graphics.Capture` probing and treats visible non-minimized Wine windows as capturable so `BitBlt` + `PostMessage` automation runs in the background without requiring foreground focus. |
| `ok/device/interaction_methods/post_message.py` | Skips `WM_ACTIVATE` spam on Wine (preventing Wine from stealing desktop focus on every click/move) and enforces a minimum `40ms` key/button hold so DXVK/UE4 frame ticks never drop fast inputs. |
| `ok/device/capture_methods/bitblt_utils.py` | Guards `capture_by_bitblt` with `IsWindow(hwnd)` before `GetWindowDC`/`BitBlt` to avoid errors on transient popups. |
| `ok/core/translation.py` | Enables `fallback=True` in `gettext.translation` so locales without compiled `.mo` files (such as `en_US`) do not raise `FileNotFoundError`. |
| `ok/util/explorer.py` | Opens folders directly via `os.startfile(..., 'explore')` instead of unimplemented `Shell.Application` COM window enumeration. |
| `ok/util/process.py` & `config.py` & `ok/__init__.py` | Skips Windows `nvidia-smi.exe` probing, launches Wuthering Waves safely via `steam://rungameid/3513350`, and coordinates pre-game standalone container handoff. |

## Repository Structure

- `setup.sh` — Automated zero-pollution installer and XDG desktop integration.
- `common.sh` — Shared Steam library, `config_info` Proton runner, Btrfs mount alias, and container-join routines.
- `ok-wuwa` — Universal launcher, container handoff supervisor, and CLI updater.
- `steam-wrapper.sh` — Optional companion wrapper for Steam Launch Options.
- `patch_wine_compat.py` — Offline-first quilt-style AST-validated Wine compatibility patcher + `sitecustomize.py` auto-repatch hook.

## License

[MIT](LICENSE)
