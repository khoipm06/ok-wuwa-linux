# OK-WuWa (Wuthering Waves Assistant) Linux & Proton Compatibility Guide

A complete guide, automated setup script, and compatibility patcher for running [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) (OK-WW) seamlessly on Linux under Steam Proton and Wine alongside Wuthering Waves.

---

## 📌 Technical Summary of Issues & Root Causes

### 1. "Game path does not exist, Please open game manually!" / "PC Disconnected"
* **Symptom**: OK-WW shows "PC Disconnected: Client-Win64-Shipping.exe" and pressing `Start(F9)` shows the red error popup *"Game path does not exist, Please open game manually!"*.
* **Root Causes**:
  1. **Wine Process Isolation**: Steam runs Wuthering Waves inside a containerized sandbox (`pressure-vessel` / bubblewrap) with its own `wineserver` instance. If OK-WW is launched from outside the container, it connects to a separate, isolated `wineserver` instance. Win32 `FindWindow("UnrealWindow")` cannot see windows across different wineservers.
  2. **`psutil` PID Query under Wine**: `ok/util/window.py` called `psutil.Process(pid)` to check process names. Under Wine, internal Windows PIDs don't match host `/proc` PIDs, causing `psutil` to fail and `find_hwnd` to discard the game window.
  3. **Direct Binary Launch Crash**: Launching `Client-Win64-Shipping.exe` directly via Windows `startfile` bypasses Steam DRM and Kuro Games Anti-Cheat (`KRSDKExternal.exe`), causing an immediate Unreal Engine **"Fatal Error!"**.
* **Fix**:
  1. Updated `window.py` with native Win32 `GetModuleFileNameEx` / `QueryFullProcessImageName` and Wine-safe window matching.
  2. Updated `config.py` so `calculate_pc_exe_path` returns `steam://rungameid/3513350` to trigger clean Steam launching without anti-cheat crashes.
  3. Launch OK-WW inside the same Proton container via **Steam Launch Options** (see below).

---

### 2. Tauri / WebView2 Launcher Disappearing Cursor
* **Symptom**: In the Tauri updater window (`ok-ww.exe`), moving the mouse into the window makes the cursor disappear.
* **Root Cause**: Microsoft Edge WebView2 (Chromium) in Wine attempts to delegate cursor rendering to DirectComposition overlays and suppresses the Win32 hardware cursor (`SetCursor(NULL)`). Under Wine, DirectComposition overlay cursors are not composited over the host X11/Wayland window.
* **Fix**: Pass `--disable-gpu --no-sandbox --disable-direct-composition --disable-gpu-compositing --disable-features=TouchEvents,TouchSelectionStrategy` to WebView2, or run `main.py` directly.

---

### 3. Black Sidebar & Titlebar (DWM Mica/Acrylic Transparency Bug)
* **Symptom**: The navigation sidebar and titlebar render completely black.
* **Root Cause**: `qfluentwidgets` and `qframelesswindow` detect Windows 11 (`build >= 22000`) and composition enabled, and activate transparent DWM Mica/Acrylic frames (`QColor(0,0,0,0)`). Under Wine, transparency without native DWM hardware compositing renders as solid black.
* **Fix**: Added dynamic Wine detection (`ntdll.wine_get_version`) to fallback to solid Fluent backgrounds (`#f0f4f9` / `#202020`).

---

### 4. PySide6 / Qt6 `QtCore` DLL Load Failure
* **Symptom**: `ImportError: DLL load failed while importing QtCore: Module not found.`
* **Root Cause**: `Qt6Core.dll` dynamically links to `icuuc.dll` and `icuin.dll`. Wine provides these in `icu.dll` without the unversioned aliases.
* **Fix**: Copy/alias `icu.dll` as `icuuc.dll` and `icuin.dll` in `system32` and `syswow64`.

---

## 🚀 Setup & Installation

### Step 1: Run Setup Script
```bash
git clone https://github.com/<your-user>/ok-wuwa-linux.git
cd ok-wuwa-linux
./setup.sh
```
*The setup script dynamically discovers your Steam libraries via `libraryfolders.vdf`, detects your Proton runner, applies all compatibility patches, and configures the wrapper scripts.*

---

### Step 2: Set Steam Launch Options

To run OK-WuWa and Wuthering Waves in the **same container & Wineserver** (so OK-WuWa connects immediately to the game window with full automation and OCR support):

1. Open **Steam** -> Right-click **Wuthering Waves** -> **Properties...**
2. In the **General** tab under **Launch Options**, paste:

* **For Flatpak Steam**:
  ```bash
  /var/mnt/LData/SteamLibrary/steamapps/compatdata/3513350/ok-wuwa-steam-wrapper.sh %command%
  ```
  *(or `~/.var/app/com.valvesoftware.Steam/ok-wuwa-steam-wrapper.sh %command%`)*

* **For Native / System Steam**:
  ```bash
  ~/.local/bin/ok-wuwa-steam-wrapper %command%
  ```

3. Launch Wuthering Waves through Steam! Both the game and OK-WuWa will start together, fully connected!

---

## 🎮 Launching Manually

* **From Application Menu**: Search for **OK-WuWa** in your desktop menu.
* **From Terminal**:
  ```bash
  ok-wuwa
  ```
* **Tauri Launcher Mode**:
  ```bash
  ok-wuwa --launcher
  ```

---

## 📜 License & Acknowledgements

* [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) by ok-oldking.
* Wuthering Waves is developed by Kuro Games.
