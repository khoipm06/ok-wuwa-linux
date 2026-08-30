#!/usr/bin/env bash
# Steam Launch Option Companion for OK-WuWa

set -e

APP_ID="3513350"
APP_NAME="OK-WuWa"

PFX_PATH="${STEAM_COMPAT_DATA_PATH:-""}"
if [ -n "$PFX_PATH" ] && [ -d "${PFX_PATH}/pfx" ]; then
    PFX_PATH="${PFX_PATH}/pfx"
fi

if [ -z "$PFX_PATH" ] || [ ! -d "$PFX_PATH" ]; then
    VDF_CANDIDATES=(
        "${HOME}/.steam/steam/steamapps/libraryfolders.vdf"
        "${HOME}/.steam/root/steamapps/libraryfolders.vdf"
        "${HOME}/.local/share/Steam/steamapps/libraryfolders.vdf"
        "${HOME}/.var/app/com.valvesoftware.Steam/data/Steam/steamapps/libraryfolders.vdf"
        "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/libraryfolders.vdf"
    )
    for vdf in "${VDF_CANDIDATES[@]}"; do
        if [ -f "$vdf" ]; then
            while IFS= read -r line; do
                if [[ "$line" =~ \"path\"[[:space:]]+\"([^\"]+)\" ]]; then
                    cand="${BASH_REMATCH[1]}/steamapps/compatdata/${APP_ID}/pfx"
                    [ -d "$cand" ] && { PFX_PATH="$cand"; break 2; }
                fi
            done < "$vdf"
        fi
    done
fi

if [ -n "$PFX_PATH" ] && [ -d "$PFX_PATH" ]; then
    APP_DIR=""
    if [ -d "${PFX_PATH}/drive_c/users" ]; then
        for u_dir in "${PFX_PATH}/drive_c/users"/*; do
            cand="${u_dir}/AppData/Local/ok-ww"
            [ -d "$cand" ] && { APP_DIR="$cand"; break; }
        done
    fi
    [ -z "$APP_DIR" ] && APP_DIR="${PFX_PATH}/drive_c/users/steamuser/AppData/Local/ok-ww"

    TARGET_EXE="${APP_DIR}/ok-ww.exe"
    TARGET_ARG=""
    PYTHON_EXE="${APP_DIR}/data/apps/ok-ww/python/python.exe"

    if [ ! -f "${TARGET_EXE}" ]; then
        MAIN_PY="${APP_DIR}/data/apps/ok-ww/working/main.py"
        if [ -f "${PYTHON_EXE}" ] && [ -f "${MAIN_PY}" ]; then
            TARGET_EXE="${PYTHON_EXE}"
            TARGET_ARG="${MAIN_PY}"
        fi
    fi

    # Detect installed WebView2 Runtime path
    WV2_DIR=""
    for check_path in "${PFX_PATH}/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application" "${PFX_PATH}/drive_c/Program Files/Microsoft/EdgeWebView/Application"; do
        if [ -d "$check_path" ]; then
            for v_dir in "$check_path"/*; do
                if [ -d "$v_dir" ] && [ -f "${v_dir}/msedgewebview2.exe" ]; then
                    v_name="$(basename "$v_dir")"
                    WV2_DIR="C:\\Program Files (x86)\\Microsoft\\EdgeWebView\\Application\\${v_name}"
                    break 2
                fi
            done
        fi
    done

    RENDER_FIX_WIN=""
    if [ "${TARGET_EXE}" = "${APP_DIR}/ok-ww.exe" ] && [ -f "${PFX_PATH}/webview2_render_fix.py" ]; then
        RENDER_FIX_WIN="Z:$(printf '%s' "${PFX_PATH}/webview2_render_fix.py" | sed 's|/|\\|g')"
    fi

    export OKWW_PROTON="${PROTON_BIN:-}"
    export OKWW_TARGET="${TARGET_EXE}"
    export OKWW_PYTHON="${PYTHON_EXE}"
    export OKWW_FIX="${RENDER_FIX_WIN}"
    export OKWW_ARGS="${TARGET_ARG}"
    INNER='if [ -z "$OKWW_FIX" ]; then exec "$OKWW_PROTON" runinprefix "$OKWW_TARGET" $OKWW_ARGS; fi
"$OKWW_PROTON" runinprefix "$OKWW_TARGET" $OKWW_ARGS &
"$OKWW_PROTON" runinprefix "$OKWW_PYTHON" "$OKWW_FIX"
wait'

    if [ -f "${TARGET_EXE}" ]; then
        (
            [ -n "$WV2_DIR" ] && export WEBVIEW2_BROWSER_EXECUTABLE_FOLDER="${WV2_DIR}"
            if [ -n "${PROTON_BIN:-}" ] && [ -x "${PROTON_BIN}" ]; then
                bash -c "$INNER" >/dev/null 2>&1 &
            elif [ -n "${STEAM_COMPAT_TOOL_PATHS:-}" ]; then
                PROTON_TOOL=$(echo "${STEAM_COMPAT_TOOL_PATHS}" | tr ':' '\n' | head -n 1)
                if [ -f "${PROTON_TOOL}/proton" ]; then
                    export OKWW_PROTON="${PROTON_TOOL}/proton"
                    bash -c "$INNER" >/dev/null 2>&1 &
                fi
            fi
        ) &
    fi
fi

exec "$@"
