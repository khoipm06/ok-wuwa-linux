#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "${SCRIPT_DIR}/common.sh"

echo "=========================================================================="
echo "                        OK-WuWa Proton Auto-Setup                         "
echo "=========================================================================="

# Auto-update repository if running inside git checkout with remote
if [ -d "${SCRIPT_DIR}/.git" ] && command -v git >/dev/null 2>&1; then
    echo "[*] Checking for latest repository patches..."
    if git -C "${SCRIPT_DIR}" remote -v 2>/dev/null | grep -q "fetch"; then
        git -C "${SCRIPT_DIR}" pull --ff-only 2>/dev/null || echo "  -> Running local build (git pull skipped or offline)."
    fi
fi

# 1. Discover Steam library folders
echo "[1/5] Discovering Steam library folders..."
steam_discover_libs
if [ ${#STEAM_LIBS[@]} -eq 0 ]; then
    STEAM_LIBS=(
        "${HOME}/.local/share/Steam"
        "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam"
    )
fi
echo "  -> Discovered ${#STEAM_LIBS[@]} Steam library folder(s)."

# 2. Locate Wuthering Waves prefix
echo "[2/5] Locating Wuthering Waves (App ID: ${APP_ID}) prefix..."
if ! steam_find_prefix; then
    echo "Error: Proton prefix for Wuthering Waves (${APP_ID}) not found."
    echo "Launch Wuthering Waves once in Steam before running setup."
    exit 1
fi
echo "  -> Found Prefix: ${PFX_PATH}"

# 3. Detect Proton Runner & Container Entry Point
echo "[3/5] Detecting installed Proton runner & container..."
steam_find_entry_point || true
if ! steam_find_proton; then
    echo "Error: No usable Proton executable found."
    exit 1
fi
echo "  -> Using Proton: ${PROTON_BIN}"

# Grant Flatpak Steam read access to the whole helper directory (wrapper,
# common.sh, and fix helpers must all be visible inside the sandbox).
steam_check_flatpak
if [ "$IS_FLATPAK" = true ] && command -v flatpak >/dev/null 2>&1; then
    echo "  -> Configuring Flatpak Steam permissions for wrapper..."
    flatpak override --user --filesystem="${HOME}/.local/share/ok-wuwa:ro" com.valvesoftware.Steam 2>/dev/null || true
fi

# 4. Check OK-WW installation
okww_find_app_dir
if [ ! -f "${APP_DIR}/ok-ww.exe" ]; then
    echo "  -> OK-WW binary not found in prefix. Downloading online installer..."
    DOWNLOAD_DIR="${PFX_PATH}/drive_c/users/steamuser/Downloads"
    mkdir -p "${DOWNLOAD_DIR}"
    INSTALLER_HOST="${DOWNLOAD_DIR}/ok-ww-online-setup.exe"
    if [ ! -f "${INSTALLER_HOST}" ]; then
        curl -L --fail -o "${INSTALLER_HOST}" "https://github.com/ok-oldking/ok-wuthering-waves/releases/latest/download/ok-ww-win32-online-setup.exe"
    fi

    echo "  -> Running installer..."
    INSTALLER_WIN="C:\\users\\steamuser\\Downloads\\ok-ww-online-setup.exe"
    TARGET_DIR="C:\\users\\steamuser\\AppData\\Local\\ok-ww"
    if [ "$IS_FLATPAK" = true ] && [ -n "${ENTRY_POINT}" ]; then
        flatpak run \
            --env=STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}" \
            --env=STEAM_COMPAT_DATA_PATH="${COMPAT_DATA_PATH}" \
            --command="${ENTRY_POINT}" \
            com.valvesoftware.Steam \
            --verb=runinprefix -- "${PROTON_BIN}" runinprefix "${INSTALLER_WIN}" /S "/D=${TARGET_DIR}" >/dev/null 2>&1 || true
    elif [ -n "${ENTRY_POINT}" ]; then
        export STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}"
        export STEAM_COMPAT_DATA_PATH="${COMPAT_DATA_PATH}"
        "${ENTRY_POINT}" --verb=runinprefix -- "${PROTON_BIN}" runinprefix "${INSTALLER_WIN}" /S "/D=${TARGET_DIR}" >/dev/null 2>&1 || true
    else
        export STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}"
        export STEAM_COMPAT_DATA_PATH="${COMPAT_DATA_PATH}"
        "${PROTON_BIN}" run "${INSTALLER_WIN}" /S "/D=${TARGET_DIR}" >/dev/null 2>&1 || true
    fi
fi

# 5. Apply Compatibility Patches
echo "[4/5] Applying Wine/Proton compatibility patches..."
python3 "${SCRIPT_DIR}/patch_wine_compat.py" "${PFX_PATH}"

# 6. Install Launchers & Conventional XDG Desktop Integration
echo "[5/5] Installing launcher scripts and desktop integration..."
mkdir -p "${HOME}/.local/bin" "${HOME}/.local/share/applications" "${HOME}/.local/share/icons/hicolor/256x256/apps" "${HOME}/.local/share/ok-wuwa"

ICON_SRC="${APP_DIR}/data/apps/ok-ww/working/icon.png"
if [ -f "${ICON_SRC}" ]; then
    cp "${ICON_SRC}" "${HOME}/.local/share/icons/hicolor/256x256/apps/ok-wuwa.png"
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true
    fi
fi

cp "${SCRIPT_DIR}/steam-wrapper.sh" "${HOME}/.local/share/ok-wuwa/steam-wrapper.sh"
chmod +x "${HOME}/.local/share/ok-wuwa/steam-wrapper.sh"

cp "${SCRIPT_DIR}/cursor_visible.py" "${HOME}/.local/share/ok-wuwa/cursor_visible.py"

cp "${SCRIPT_DIR}/webview2_render_fix.py" "${HOME}/.local/share/ok-wuwa/webview2_render_fix.py"

cp "${SCRIPT_DIR}/ok-wuwa" "${HOME}/.local/bin/ok-wuwa"
chmod +x "${HOME}/.local/bin/ok-wuwa"

DESKTOP_PATH="${HOME}/.local/share/applications/ok-wuwa.desktop"
cat << DESKTOP_EOF > "${DESKTOP_PATH}"
[Desktop Entry]
Name=OK-WuWa
Comment=Wuthering Waves Automation Assistant
Exec=${HOME}/.local/bin/ok-wuwa
Icon=ok-wuwa
Terminal=false
Type=Application
Categories=Game;Utility;
StartupNotify=true
DESKTOP_EOF
chmod +x "${DESKTOP_PATH}"

echo "=========================================================================="
echo " Setup Complete!"
echo " 1. Run independently anytime:"
echo "    \`ok-wuwa\` in shell or launch from the desktop menu."
echo ""
echo " 2. (Optional) Run alongside Wuthering Waves via Steam Launch Options:"
echo "    Steam -> Wuthering Waves -> Properties -> Launch Options:"
echo "    ~/.local/share/ok-wuwa/steam-wrapper.sh %command%"
echo "=========================================================================="
