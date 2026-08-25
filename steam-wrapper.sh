#!/usr/bin/env bash
# ==============================================================================
# Optional Steam Companion Launch Option Wrapper for Wuthering Waves + OK-WuWa
#
# Usage in Steam -> Wuthering Waves -> Properties -> Launch Options:
#   ~/.local/bin/ok-wuwa-steam-wrapper %command%
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
        
        APP_DIR=""
        for base in "${STEAM_COMPAT_DATA_PATH}" "${HOME}"; do
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
            APP_DIR=$(find "${STEAM_COMPAT_DATA_PATH:-${HOME}}" -path "*/AppData/Local/ok-ww/data/apps/ok-ww/working" -type d 2>/dev/null | head -n 1 || true)
            [ -n "$APP_DIR" ] && APP_DIR="$(dirname "$(dirname "$(dirname "$APP_DIR")")")"
        fi

        WORKING_DIR="${APP_DIR}/data/apps/ok-ww/working"
        PYTHON_EXE="C:\\users\\steamuser\\AppData\\Local\\ok-ww\\data\\apps\\ok-ww\\python\\python.exe"
        MAIN_PY="C:\\users\\steamuser\\AppData\\Local\\ok-ww\\data\\apps\\ok-ww\\working\\main.py"
        LOG_DIR="${WORKING_DIR}/logs"
        mkdir -p "${LOG_DIR}"
        WRAPPER_LOG="${LOG_DIR}/steam_wrapper.log"

        echo "[$(date)] Starting OK-WuWa companion via Steam Launch Options..." >> "${WRAPPER_LOG}"
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
                "${ENTRY_POINT}" --verb=runinprefix -- "${PROTON_BIN}" runinprefix "${PYTHON_EXE}" "${MAIN_PY}" >> "${WRAPPER_LOG}" 2>&1
            elif [ -n "${PROTON_BIN}" ]; then
                "${PROTON_BIN}" run "${PYTHON_EXE}" "${MAIN_PY}" >> "${WRAPPER_LOG}" 2>&1
            fi
        fi
    fi
) &
COMPANION_PID=$!

wait "${GAME_PID}"
