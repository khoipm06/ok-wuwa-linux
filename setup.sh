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
                if [ -d "$lib_path" ]; then
                    STEAM_LIBS+=("$lib_path")
                fi
            fi
        done < "$vdf"
    fi
done

# Deduplicate
if [ ${#STEAM_LIBS[@]} -gt 0 ]; then
    readarray -t STEAM_LIBS < <(printf '%s\n' "${STEAM_LIBS[@]}" | sort -u)
fi

# Fallbacks if VDF was not found
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
    if [ -d "$cand" ]; then
        PFX_PATH="$cand"
        break
    fi
done

if [ -z "$PFX_PATH" ]; then
    # Fallback to search mounted filesystems
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
PROTON_DIR=""
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
        if [ -n "$cand" ] && [ -x "$cand" ]; then
            PROTON_BIN="$cand"
            PROTON_DIR="$(dirname "$cand")"
            break
        fi
    fi
done

if [ -z "$PROTON_BIN" ]; then
    for dir in "${PROTON_SEARCH_DIRS[@]}"; do
        if [ -d "$dir" ]; then
            cand=$(find "$dir" -maxdepth 3 -name "proton" -type f -perm -111 2>/dev/null | head -n 1 || true)
            if [ -n "$cand" ] && [ -x "$cand" ]; then
                PROTON_BIN="$cand"
                PROTON_DIR="$(dirname "$cand")"
                break
            fi
        fi
    done
fi

if [ -z "$PROTON_BIN" ] || [ ! -x "$PROTON_BIN" ]; then
    echo "Error: Could not automatically detect a Proton executable."
    exit 1
fi
echo "  -> Using Proton: ${PROTON_BIN}"

# Detect primary Steam client directory
STEAM_CLIENT_PATH="${HOME}/.local/share/Steam"
if [ -d "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam" ]; then
    STEAM_CLIENT_PATH="${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam"
fi

# 4. Check if OK-WW is installed, download installer if missing
APP_DIR=""
for u in "steamuser" "${USER}" "default"; do
    cand="${PFX_PATH}/drive_c/users/${u}/AppData/Local/ok-ww"
    if [ -d "$cand" ]; then
        APP_DIR="$cand"
        break
    fi
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

# 6. Install System Launcher and Steam Wrapper
echo "[5/5] Creating launcher scripts and desktop integration..."
mkdir -p "${HOME}/.local/bin" "${HOME}/.local/share/applications" "${HOME}/.local/share/icons"

# Extract App Icon if available
ICON_SRC="${APP_DIR}/data/apps/ok-ww/working/icon.png"
if [ -f "${ICON_SRC}" ]; then
    cp "${ICON_SRC}" "${HOME}/.local/share/icons/ok-wuwa.png"
fi

# 6a. Standalone Independent Launcher Script (~/.local/bin/ok-wuwa)
LAUNCHER_PATH="${HOME}/.local/bin/ok-wuwa"
cat << 'LAUNCHER_EOF' > "${LAUNCHER_PATH}"
#!/usr/bin/env bash
set -e

APP_ID="3513350"
APP_NAME="OK-WuWa"

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

# Deduplicate
if [ ${#STEAM_LIBS[@]} -gt 0 ]; then
    readarray -t STEAM_LIBS < <(printf '%s
' "${STEAM_LIBS[@]}" | sort -u)
fi

# 2. Locate Prefix for Wuthering Waves (3513350)
PFX_PATH=""
for lib in "${STEAM_LIBS[@]}"; do
    cand="${lib}/steamapps/compatdata/${APP_ID}/pfx"
    [ -d "$cand" ] && { PFX_PATH="$cand"; break; }
done

if [ -z "$PFX_PATH" ]; then
    PFX_PATH=$(find /var/mnt /mnt /run/media "${HOME}" -path "*/steamapps/compatdata/${APP_ID}/pfx" -type d 2>/dev/null | head -n 1 || true)
fi

if [ -z "$PFX_PATH" ] || [ ! -d "$PFX_PATH" ]; then
    echo "Error: Prefix for App ID ${APP_ID} not found. Launch Wuthering Waves once via Steam first." >&2
    exit 1
fi

COMPAT_DATA_PATH="$(dirname "${PFX_PATH}")"

# 3. Locate Steam Linux Runtime container entry point (_v2-entry-point)
ENTRY_POINT=""
for lib in "${STEAM_LIBS[@]}"; do
    cand=$(find "${lib}/steamapps/common" -maxdepth 3 -name "_v2-entry-point" -type f -perm -111 2>/dev/null | sort -V | tail -n 1 || true)
    [ -n "$cand" ] && { ENTRY_POINT="$cand"; break; }
done

# 4. Locate Proton runner
PROTON_BIN=""
SEARCH_DIRS=(
    "${HOME}/.steam/root/compatibilitytools.d"
    "${HOME}/.local/share/Steam/compatibilitytools.d"
    "${HOME}/.var/app/com.valvesoftware.Steam/data/Steam/compatibilitytools.d"
    "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d"
)
for lib in "${STEAM_LIBS[@]}"; do
    SEARCH_DIRS+=("${lib}/compatibilitytools.d" "${lib}/steamapps/common")
done

for dir in "${SEARCH_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        cand=$(find "$dir" -maxdepth 3 -name "proton" -type f -perm -111 2>/dev/null | grep -E "Proton-CachyOS|GE-Proton|Proton - Experimental|Proton [0-9]" | head -n 1 || true)
        [ -n "$cand" ] && [ -x "$cand" ] && { PROTON_BIN="$cand"; break; }
    fi
done

if [ -z "$PROTON_BIN" ]; then
    for dir in "${SEARCH_DIRS[@]}"; do
        if [ -d "$dir" ]; then
            cand=$(find "$dir" -maxdepth 3 -name "proton" -type f -perm -111 2>/dev/null | head -n 1 || true)
            [ -n "$cand" ] && [ -x "$cand" ] && { PROTON_BIN="$cand"; break; }
        fi
    done
fi

# 5. Check if Flatpak Steam is used
IS_FLATPAK=false
STEAM_CLIENT_PATH="${HOME}/.local/share/Steam"
if [ -d "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam" ] || (command -v flatpak >/dev/null && flatpak info com.valvesoftware.Steam >/dev/null 2>&1); then
    IS_FLATPAK=true
    STEAM_CLIENT_PATH="${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam"
fi

# 6. Locate OK-WW application directory
APP_DIR=""
for u in "steamuser" "${USER}" "default" "steamuser"; do
    cand="${PFX_PATH}/drive_c/users/${u}/AppData/Local/ok-ww"
    [ -d "$cand" ] && { APP_DIR="$cand"; break; }
done

[ -z "$APP_DIR" ] && APP_DIR="${PFX_PATH}/drive_c/users/steamuser/AppData/Local/ok-ww"
WORKING_DIR="${APP_DIR}/data/apps/ok-ww/working"
PYTHON_EXE="C:\users\steamuser\AppData\Local\ok-ww\data\apps\ok-ww\python\python.exe"
MAIN_PY="C:\users\steamuser\AppData\Local\ok-ww\data\apps\ok-ww\working\main.py"
LAUNCHER_EXE="C:\users\steamuser\AppData\Local\ok-ww\ok-ww.exe"

export WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--disable-gpu --no-sandbox --disable-direct-composition --disable-gpu-compositing --disable-features=TouchEvents,TouchSelectionStrategy"

# 7. Execute OK-WuWa inside the Steam Linux Runtime container
TARGET_EXE="${PYTHON_EXE}"
TARGET_ARG="${MAIN_PY}"

if [ "$1" = "--launcher" ] || [ "$1" = "--updater" ]; then
    TARGET_EXE="${LAUNCHER_EXE}"
    TARGET_ARG=""
    shift
fi

if [ "$IS_FLATPAK" = true ] && [ -n "${ENTRY_POINT}" ]; then
    exec flatpak run \
        --env=STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}" \
        --env=STEAM_COMPAT_DATA_PATH="${COMPAT_DATA_PATH}" \
        --env=WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="${WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS}" \
        --command="${ENTRY_POINT}" \
        com.valvesoftware.Steam \
        --verb=runinprefix -- "${PROTON_BIN}" runinprefix "${TARGET_EXE}" ${TARGET_ARG:+"$TARGET_ARG"} "$@"
elif [ -n "${ENTRY_POINT}" ]; then
    export STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}"
    export STEAM_COMPAT_DATA_PATH="${COMPAT_DATA_PATH}"
    cd "${WORKING_DIR}"
    exec "${ENTRY_POINT}" --verb=runinprefix -- "${PROTON_BIN}" runinprefix "${TARGET_EXE}" ${TARGET_ARG:+"$TARGET_ARG"} "$@"
else
    export STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}"
    export STEAM_COMPAT_DATA_PATH="${COMPAT_DATA_PATH}"
    cd "${WORKING_DIR}"
    exec "${PROTON_BIN}" run "${TARGET_EXE}" ${TARGET_ARG:+"$TARGET_ARG"} "$@"
fi
LAUNCHER_EOF
chmod +x "${LAUNCHER_PATH}"


# 6b. Steam Launch Options Wrapper
WRAPPER_PATH="${HOME}/.local/bin/ok-wuwa-steam-wrapper"
COMPAT_WRAPPER="${COMPAT_DATA_PATH}/ok-wuwa-steam-wrapper.sh"
cat << 'WRAPPER_EOF' > "${WRAPPER_PATH}"
#!/usr/bin/env bash
# ==============================================================================
# Universal Steam Companion Wrapper for Wuthering Waves + OK-WuWa
# ==============================================================================

cleanup() {
    [ -n "$COMPANION_PID" ] && kill "$COMPANION_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# 1. Launch primary game command in background
"$@" &
GAME_PID=$!

# 2. Extract container runner and proton binary from Steam invocation
ENTRY_POINT=""
PROTON_BIN=""

for arg in "$@"; do
    if [[ "$arg" == *"_v2-entry-point"* ]]; then
        ENTRY_POINT="$arg"
    elif [[ "$arg" == *"/proton"* ]] || [[ "$arg" == *"proton" && -x "$arg" ]]; then
        PROTON_BIN="$arg"
    fi
done

# 3. Launch OK-WuWa companion in background
(
    set +e
    sleep 7

    if kill -0 "${GAME_PID}" 2>/dev/null; then
        export WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--disable-gpu --no-sandbox --disable-direct-composition --disable-gpu-compositing --disable-features=TouchEvents,TouchSelectionStrategy"
        
        SCRIPT_PFX="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        APP_DIR=""
        
        for base in "${STEAM_COMPAT_DATA_PATH}" "${SCRIPT_PFX}" "${HOME}"; do
            if [ -n "$base" ]; then
                for u in "steamuser" "${USER}" "default" "steamuser"; do
                    cand="${base}/pfx/drive_c/users/${u}/AppData/Local/ok-ww"
                    [ -d "$cand" ] && { APP_DIR="$cand"; break 2; }
                    cand="${base}/drive_c/users/${u}/AppData/Local/ok-ww"
                    [ -d "$cand" ] && { APP_DIR="$cand"; break 2; }
                done
            fi
        done

        if [ -z "$APP_DIR" ]; then
            APP_DIR=$(find "${STEAM_COMPAT_DATA_PATH:-${SCRIPT_PFX}}" -path "*/AppData/Local/ok-ww/data/apps/ok-ww/working" -type d 2>/dev/null | head -n 1 || true)
            [ -n "$APP_DIR" ] && APP_DIR="$(dirname "$(dirname "$(dirname "$APP_DIR")")")"
        fi

        WORKING_DIR="${APP_DIR}/data/apps/ok-ww/working"
        PYTHON_EXE="C:\users\steamuser\AppData\Local\ok-ww\data\apps\ok-ww\python\python.exe"
        LOG_DIR="${WORKING_DIR}/logs"
        mkdir -p "${LOG_DIR}"
        WRAPPER_LOG="${LOG_DIR}/steam_wrapper.log"

        echo "[$(date)] Starting OK-WuWa companion..." >> "${WRAPPER_LOG}"
        echo "  Entry point: ${ENTRY_POINT}" >> "${WRAPPER_LOG}"
        echo "  Proton: ${PROTON_BIN}" >> "${WRAPPER_LOG}"
        echo "  App Dir: ${APP_DIR}" >> "${WRAPPER_LOG}"

        # If Proton was not in command line, find it dynamically
        if [ -z "${PROTON_BIN}" ]; then
            for p_dir in "${HOME}/.local/share/Steam/compatibilitytools.d" "${HOME}/compatibilitytools.d" "${HOME}/.steam/root/compatibilitytools.d" "/app/share/steam/compatibilitytools.d"; do
                if [ -d "$p_dir" ]; then
                    cand=$(find "$p_dir" -maxdepth 3 -name "proton" -type f -perm -111 2>/dev/null | grep -E "Proton-CachyOS|GE-Proton|Proton - Experimental|Proton [0-9]" | head -n 1 || true)
                    [ -n "$cand" ] && { PROTON_BIN="$cand"; break; }
                fi
            done
        fi

        if [ -d "${WORKING_DIR}" ]; then
            cd "${WORKING_DIR}"
            if [ -n "${ENTRY_POINT}" ] && [ -n "${PROTON_BIN}" ]; then
                "${ENTRY_POINT}" --verb=runinprefix -- "${PROTON_BIN}" runinprefix "${PYTHON_EXE}" "main.py" >> "${WRAPPER_LOG}" 2>&1
            elif [ -n "${PROTON_BIN}" ]; then
                "${PROTON_BIN}" run "${PYTHON_EXE}" "main.py" >> "${WRAPPER_LOG}" 2>&1
            else
                echo "Error: Proton binary not found" >> "${WRAPPER_LOG}"
            fi
        else
            echo "Error: Working directory not found: ${WORKING_DIR}" >> "${WRAPPER_LOG}"
        fi
    fi
) &
COMPANION_PID=$!

wait "${GAME_PID}"
WRAPPER_EOF
chmod +x "${WRAPPER_PATH}"
cp "${WRAPPER_PATH}" "${COMPAT_WRAPPER}"
chmod +x "${COMPAT_WRAPPER}"
[ -d "${HOME}/.var/app/com.valvesoftware.Steam" ] && cp "${WRAPPER_PATH}" "${HOME}/.var/app/com.valvesoftware.Steam/ok-wuwa-steam-wrapper.sh"


# 6c. Desktop Entry (~/.local/share/applications/ok-wuwa.desktop)
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
echo " 1. To run alongside Wuthering Waves via Steam (Recommended):"
echo "    Steam -> Wuthering Waves -> Properties -> Launch Options:"
echo "    ~/.local/bin/ok-wuwa-steam-wrapper %command%"
echo ""
echo " 2. To run manually:"
echo "    ok-wuwa"
echo "=========================================================="
