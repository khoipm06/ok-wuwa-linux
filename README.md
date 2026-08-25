# OK-WuWa (Wuthering Waves Assistant) Linux & Proton Compatibility Guide

A complete guide, automated setup script, and compatibility patcher for running [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) (OK-WW) seamlessly on Linux under Steam Proton, Flatpak Steam, Native Steam, and Wine alongside Wuthering Waves.

---

## 📌 Architecture & Design

This repository is designed to give Linux users the exact same seamless experience as on Windows:

1. **Independent Execution**:
   * **Workflow A**: Start Wuthering Waves in Steam ➔ Open OK-WuWa at any time. OK-WuWa automatically enters the active Steam container and connects to the game window immediately.
   * **Workflow B**: Open OK-WuWa first ➔ Click **Start** (or press `F9`). OK-WuWa launches Wuthering Waves via Steam protocol (`steam://rungameid/3513350`) and connects automatically.
2. **Container Sharing via Steam Linux Runtime**:
   * Uses Valve's official `_v2-entry-point --verb=runinprefix` to share the `pressure-vessel` container and `wineserver` across both Flatpak and Native Steam installations.
3. **100% Dynamic Discovery**:
   * Automatically parses `libraryfolders.vdf` across all drives, mount points, and Proton runners without any hardcoded paths.

---

## 🔧 Technical Summary of Fixes Applied

| Component | Issue on Wine/Linux | Solution |
| :--- | :--- | :--- |
| **System DLLs** | `Qt6Core.dll` fails to load unversioned `icuuc.dll` / `icuin.dll`. | Aliased `icu.dll` in Wine `system32` & `syswow64`. |
| **DWM Glass & Transparency** | Win11 DWM backdrop transparency renders sidebar/titlebar pitch black. | Bypassed DWM Mica on Wine and restored solid Fluent backgrounds (`#f0f4f9` / `#202020`). |
| **Cursor Visibility** | DirectComposition glass extension hides mouse cursor on Wine. | Disabled DWM full-window glass extension and set explicit cursor tracking. |
| **Window & Focus Detection** | Wine `GetForegroundWindow()` state jitter caused focus flapping every second. | Updated `is_foreground_window` on Wine to check window visibility and minimized state. |
| **Input Responsiveness** | Fast 10ms key/click duration caused dropped skills (E, Q, R, middle-click) on DXVK. | Synchronized input `down_time` to 40ms (`0.04s`) across all combat modules. |
| **BitBlt Crash Loops** | Closed popup handles caused repeating `(1400, GetWindowDC)` exceptions. | Added `win32gui.IsWindow(hwnd)` handle validation before DC creation. |
| **Anti-Cheat Safe Launch** | Direct binary launch causes anti-cheat "Fatal Error" crashes. | Resolved launch path to `steam://rungameid/3513350` to initialize DRM and anti-cheat properly. |

---

## 🚀 Setup & Installation

### Step 1: Clone and Run Setup
```bash
git clone https://github.com/<your-user>/ok-wuwa-linux.git
cd ok-wuwa-linux
./setup.sh
```
*The setup script detects your Steam libraries, applies all compatibility patches to the Wine prefix, and installs the launcher into `~/.local/bin/ok-wuwa`.*

---

### Step 2: Running OK-WuWa

#### Option A: Independent Launch (Recommended)
You can run OK-WuWa at any time from your application menu or terminal:
```bash
ok-wuwa
```
*(Tauri Updater mode: `ok-wuwa --launcher`)*

#### Option B: Optional Steam Launch Option
If you prefer OK-WuWa to start automatically whenever you launch the game from Steam:
1. In Steam, right-click **Wuthering Waves** ➔ **Properties...** ➔ **Launch Options**.
2. Paste:
   ```bash
   ~/.local/bin/ok-wuwa-steam-wrapper %command%
   ```

---

## 📜 License & Acknowledgements

* [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) by ok-oldking.
* Wuthering Waves is developed by Kuro Games.
