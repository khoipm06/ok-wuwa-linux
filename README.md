# OK-WuWa on Linux

Run [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) on Linux under Steam Proton, Flatpak Steam, and Wine.

## Prerequisites

- Wuthering Waves installed and run once in Steam.
- Python 3 on your host system.

## Quick Start

```bash
git clone https://github.com/your-username/ok-wuwa-linux.git
cd ok-wuwa-linux
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
- Start OK-WuWa, then click **Start** in the UI to launch Wuthering Waves.
- Start Wuthering Waves in Steam first, then launch OK-WuWa.

### Optional: 1-Click Steam Integration

To start OK-WuWa automatically whenever you launch Wuthering Waves from Steam:

1. Open Steam, right-click **Wuthering Waves**, and select **Properties**.
2. Set **Launch Options** to:
   ```bash
   ~/.local/bin/ok-wuwa-steam-wrapper %command%
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

- `setup.sh`: Automated setup and prefix patcher.
- `ok-wuwa`: Standalone desktop launcher for `ok-ww.exe`.
- `steam-wrapper.sh`: Companion wrapper for Steam launch options.
- `patch_wine_compat.py`: Safe, reversible Wine patch engine.
