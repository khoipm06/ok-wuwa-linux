#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="3513350"
APP_NAME="OK-WuWa"

echo "=========================================================="
echo "    OK-WuWa (Wuthering Waves) Linux / Proton Auto-Setup   "
echo "=========================================================="

# 1. Dynamically locate Steam library folders
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

# Deduplicate
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

# 2. Locate Wuthering Waves prefix (compatdata/3513350)
echo "[2/5] Locating Wuthering Waves (App ID: ${APP_ID}) prefix..."
PFX_PATH=""
for lib in "${STEAM_LIBS[@]}"; do
    cand="${lib}/steamapps/compatdata/${APP_ID}/pfx"
    [ -d "$cand" ] && { PFX_PATH="$cand"; break; }
done

if [ -z "$PFX_PATH" ]; then
    PFX_PATH=$(find /var/mnt /mnt /run/media "${HOME}" -path "*/steamapps/compatdata/${APP_ID}/pfx" -type d 2>/dev/null | head -n 1 || true)
fi

if [ -z "$PFX_PATH" ] || [ ! -d "$PFX_PATH" ]; then
    echo "Error: Could not locate Proton prefix for Wuthering Waves (${APP_ID})."
    echo "Please install and launch Wuthering Waves at least once via Steam before running setup."
    exit 1
fi
echo "  -> Found Prefix: ${PFX_PATH}"
COMPAT_DATA_PATH="$(dirname "${PFX_PATH}")"

# 3. Detect Proton Runner
echo "[3/5] Detecting installed Proton runner..."
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
    echo "Error: Could not automatically detect a Proton executable."
    exit 1
fi
echo "  -> Using Proton: ${PROTON_BIN}"

STEAM_CLIENT_PATH="${HOME}/.local/share/Steam"
if [ -d "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam" ]; then
    STEAM_CLIENT_PATH="${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam"
fi

# 4. Check if OK-WW is installed, download installer if missing
APP_DIR=""
for u in "steamuser" "${USER}" "default" "steamuser"; do
    cand="${PFX_PATH}/drive_c/users/${u}/AppData/Local/ok-ww"
    [ -d "$cand" ] && { APP_DIR="$cand"; break; }
done

if [ -z "$APP_DIR" ]; then
    APP_DIR="${PFX_PATH}/drive_c/users/steamuser/AppData/Local/ok-ww"
fi

if [ ! -d "${APP_DIR}" ]; then
    echo "  -> OK-WW not found in prefix. Downloading latest installer..."
    TMP_INSTALLER="/tmp/ok-ww-setup.exe"
    curl -L -o "${TMP_INSTALLER}" "https://github.com/ok-oldking/ok-wuthering-waves/releases/latest/download/ok-ww-setup.exe"
    echo "  -> Running installer in prefix..."
    STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}" \
    STEAM_COMPAT_DATA_PATH="${COMPAT_DATA_PATH}" \
    "${PROTON_BIN}" run "${TMP_INSTALLER}"
fi

# 5. Apply Compatibility Patches
echo "[4/5] Applying Wine/Proton compatibility patches..."
python3 "${SCRIPT_DIR}/patch_wine_compat.py" "${PFX_PATH}"

# 6. Install System Launcher and Steam Wrapper from repository
echo "[5/5] Installing launcher scripts and desktop integration..."
mkdir -p "${HOME}/.local/bin" "${HOME}/.local/share/applications" "${HOME}/.local/share/icons"

# Extract App Icon if available
ICON_SRC="${APP_DIR}/data/apps/ok-ww/working/icon.png"
if [ -f "${ICON_SRC}" ]; then
    cp "${ICON_SRC}" "${HOME}/.local/share/icons/ok-wuwa.png"
fi

# Copy scripts directly from repository into ~/.local/bin
cp "${SCRIPT_DIR}/ok-wuwa" "${HOME}/.local/bin/ok-wuwa"
chmod +x "${HOME}/.local/bin/ok-wuwa"

cp "${SCRIPT_DIR}/steam-wrapper.sh" "${HOME}/.local/bin/ok-wuwa-steam-wrapper"
chmod +x "${HOME}/.local/bin/ok-wuwa-steam-wrapper"

# Desktop Entry (~/.local/share/applications/ok-wuwa.desktop)
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

echo "=========================================================="
echo " Setup Complete!"
echo " 1. Run independently anytime (Game first OR OK-WuWa first):"
echo "    ok-wuwa"
echo ""
echo " 2. (Optional) Run alongside Wuthering Waves via Steam Launch Options:"
echo "    Steam -> Wuthering Waves -> Properties -> Launch Options:"
echo "    ~/.local/bin/ok-wuwa-steam-wrapper %command%"
echo "=========================================================="
