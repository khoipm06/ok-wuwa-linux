#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="3513350"
APP_NAME="OK-WuWa"

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
VDF_CANDIDATES=(
    "${HOME}/.steam/steam/steamapps/libraryfolders.vdf"
    "${HOME}/.steam/root/steamapps/libraryfolders.vdf"
    "${HOME}/.local/share/Steam/steamapps/libraryfolders.vdf"
    "${HOME}/.var/app/com.valvesoftware.Steam/data/Steam/steamapps/libraryfolders.vdf"
    "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/libraryfolders.vdf"
)

STEAM_LIBS=()
for vdf in "${VDF_CANDIDATES[@]}"; do
    if [ -f "$vdf" ]; then
        while IFS= read -r line; do
            if [[ "$line" =~ \"path\"[[:space:]]+\"([^\"]+)\" ]]; then
                lib_path="${BASH_REMATCH[1]}"
                [ -d "$lib_path" ] && STEAM_LIBS+=("$lib_path")
            fi
        done < "$vdf"
    fi
done

if [ ${#STEAM_LIBS[@]} -gt 0 ]; then
    readarray -t STEAM_LIBS < <(printf '%s\n' "${STEAM_LIBS[@]}" | sort -u)
fi

if [ ${#STEAM_LIBS[@]} -eq 0 ]; then
    STEAM_LIBS=(
        "${HOME}/.local/share/Steam"
        "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam"
    )
fi
echo "  -> Discovered ${#STEAM_LIBS[@]} Steam library folder(s)."

# 2. Locate Wuthering Waves prefix
echo "[2/5] Locating Wuthering Waves (App ID: ${APP_ID}) prefix..."
PFX_PATH=""
for lib in "${STEAM_LIBS[@]}"; do
    cand="${lib}/steamapps/compatdata/${APP_ID}/pfx"
    [ -d "$cand" ] && { PFX_PATH="$cand"; break; }
done

if [ -z "$PFX_PATH" ]; then
    SEARCH_ROOTS=()
    for root in "/var/mnt" "/mnt" "/media" "/run/media/${USER}" "${HOME}"; do
        [ -d "$root" ] && SEARCH_ROOTS+=("$root")
    done
    if [ ${#SEARCH_ROOTS[@]} -gt 0 ]; then
        PFX_PATH=$(find "${SEARCH_ROOTS[@]}" -maxdepth 5 -path "*/steamapps/compatdata/${APP_ID}/pfx" -type d 2>/dev/null | head -n 1 || true)
    fi
fi

if [ -z "$PFX_PATH" ] || [ ! -d "$PFX_PATH" ]; then
    echo "Error: Proton prefix for Wuthering Waves (${APP_ID}) not found."
    echo "Launch Wuthering Waves once in Steam before running setup."
    exit 1
fi
echo "  -> Found Prefix: ${PFX_PATH}"
COMPAT_DATA_PATH="$(dirname "${PFX_PATH}")"

# 3. Detect Proton Runner & Container Entry Point
echo "[3/5] Detecting installed Proton runner & container..."
ENTRY_POINT=""
for lib in "${STEAM_LIBS[@]}"; do
    cand=$(find "${lib}/steamapps/common" -maxdepth 3 -name "_v2-entry-point" -type f -perm -111 2>/dev/null | sort -V | tail -n 1 || true)
    [ -n "$cand" ] && { ENTRY_POINT="$cand"; break; }
done

PROTON_BIN=""
PROTON_SEARCH_DIRS=(
    "${HOME}/.steam/root/compatibilitytools.d"
    "${HOME}/.local/share/Steam/compatibilitytools.d"
    "${HOME}/.var/app/com.valvesoftware.Steam/data/Steam/compatibilitytools.d"
    "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d"
)

for lib in "${STEAM_LIBS[@]}"; do
    PROTON_SEARCH_DIRS+=("${lib}/compatibilitytools.d" "${lib}/steamapps/common")
done

for dir in "${PROTON_SEARCH_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        cand=$(find "$dir" -maxdepth 3 -name "proton" -type f -perm -111 2>/dev/null | grep -E "Proton-CachyOS|GE-Proton|Proton - Experimental|Proton [0-9]" | head -n 1 || true)
        [ -n "$cand" ] && [ -x "$cand" ] && { PROTON_BIN="$cand"; break; }
    fi
done

if [ -z "$PROTON_BIN" ]; then
    for dir in "${PROTON_SEARCH_DIRS[@]}"; do
        if [ -d "$dir" ]; then
            cand=$(find "$dir" -maxdepth 3 -name "proton" -type f -perm -111 2>/dev/null | head -n 1 || true)
            [ -n "$cand" ] && [ -x "$cand" ] && { PROTON_BIN="$cand"; break; }
        fi
    done
fi

if [ -z "$PROTON_BIN" ] || [ ! -x "$PROTON_BIN" ]; then
    echo "Error: No usable Proton executable found."
    exit 1
fi
echo "  -> Using Proton: ${PROTON_BIN}"

# Check Flatpak Steam and grant specific file permission for wrapper
IS_FLATPAK=false
STEAM_CLIENT_PATH="${HOME}/.local/share/Steam"
if [ -d "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam" ] || (command -v flatpak >/dev/null && flatpak info com.valvesoftware.Steam >/dev/null 2>&1); then
    IS_FLATPAK=true
    STEAM_CLIENT_PATH="${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam"
    if command -v flatpak >/dev/null 2>&1; then
        echo "  -> Configuring Flatpak Steam permissions for wrapper..."
        flatpak override --user --filesystem="${HOME}/.local/share/ok-wuwa:ro" com.valvesoftware.Steam 2>/dev/null || true
    fi
fi

# 4. Check OK-WW installation
APP_DIR=""
if [ -d "${PFX_PATH}/drive_c/users" ]; then
    for u_dir in "${PFX_PATH}/drive_c/users"/*; do
        cand="${u_dir}/AppData/Local/ok-ww"
        [ -d "$cand" ] && { APP_DIR="$cand"; break; }
    done
fi

if [ -z "$APP_DIR" ]; then
    APP_DIR="${PFX_PATH}/drive_c/users/steamuser/AppData/Local/ok-ww"
fi

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
