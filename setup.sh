#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="3513350"
APP_NAME="OK-WuWa"

echo "=== OK-WuWa Linux / Proton Setup ==="

# 1. Discover Steam library folders
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

# 2. Locate Wuthering Waves prefix
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
echo "Found Prefix: ${PFX_PATH}"
COMPAT_DATA_PATH="$(dirname "${PFX_PATH}")"

# Clean up any legacy scripts from prefix
rm -f "${COMPAT_DATA_PATH}/ok-wuwa-steam-wrapper.sh" "${HOME}/.var/app/com.valvesoftware.Steam/ok-wuwa-steam-wrapper.sh"

# 3. Detect Proton Runner
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
echo "Using Proton: ${PROTON_BIN}"

# Check Flatpak Steam and grant ~/.local/bin filesystem access
IS_FLATPAK=false
STEAM_CLIENT_PATH="${HOME}/.local/share/Steam"
if [ -d "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam" ] || (command -v flatpak >/dev/null && flatpak info com.valvesoftware.Steam >/dev/null 2>&1); then
    IS_FLATPAK=true
    STEAM_CLIENT_PATH="${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam"
    if command -v flatpak >/dev/null 2>&1; then
        echo "Configuring Flatpak Steam sandbox permissions..."
        flatpak override --user --filesystem="${HOME}/.local/bin:ro" com.valvesoftware.Steam 2>/dev/null || true
    fi
fi

# 4. Check OK-WW installation
APP_DIR=""
for u in "steamuser" "${USER}" "default" "steamuser"; do
    cand="${PFX_PATH}/drive_c/users/${u}/AppData/Local/ok-ww"
    [ -d "$cand" ] && { APP_DIR="$cand"; break; }
done

if [ -z "$APP_DIR" ]; then
    APP_DIR="${PFX_PATH}/drive_c/users/steamuser/AppData/Local/ok-ww"
fi

if [ ! -d "${APP_DIR}" ]; then
    echo "OK-WW not found in prefix. Downloading installer..."
    TMP_INSTALLER="/tmp/ok-ww-setup.exe"
    curl -L -o "${TMP_INSTALLER}" "https://github.com/ok-oldking/ok-wuthering-waves/releases/latest/download/ok-ww-setup.exe"
    echo "Running installer..."
    STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}" \
    STEAM_COMPAT_DATA_PATH="${COMPAT_DATA_PATH}" \
    "${PROTON_BIN}" run "${TMP_INSTALLER}"
fi

# 5. Apply Compatibility Patches
python3 "${SCRIPT_DIR}/patch_wine_compat.py" "${PFX_PATH}"

# 6. Install Launchers & Conventional XDG Desktop Integration
mkdir -p "${HOME}/.local/bin" "${HOME}/.local/share/applications" "${HOME}/.local/share/icons/hicolor/256x256/apps"

ICON_SRC="${APP_DIR}/data/apps/ok-ww/working/icon.png"
if [ -f "${ICON_SRC}" ]; then
    cp "${ICON_SRC}" "${HOME}/.local/share/icons/hicolor/256x256/apps/ok-wuwa.png"
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true
    fi
fi

cp "${SCRIPT_DIR}/ok-wuwa" "${HOME}/.local/bin/ok-wuwa"
chmod +x "${HOME}/.local/bin/ok-wuwa"

cp "${SCRIPT_DIR}/steam-wrapper.sh" "${HOME}/.local/bin/ok-wuwa-steam-wrapper"
chmod +x "${HOME}/.local/bin/ok-wuwa-steam-wrapper"

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

echo ""
echo "Setup finished."
echo "- Run from app launcher or terminal: ok-wuwa"
echo "- Optional Steam Launch Option: ~/.local/bin/ok-wuwa-steam-wrapper %command%"
