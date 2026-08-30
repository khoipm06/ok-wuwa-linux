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

    if [ ! -f "${TARGET_EXE}" ]; then
        PYTHON_EXE="${APP_DIR}/data/apps/ok-ww/python/python.exe"
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

    WV2_FLAGS="--no-sandbox --disable-gpu --disable-gpu-compositing --disable-gpu-rasterization --in-process-gpu --disable-features=RendererCodeIntegrity,TouchEvents,TouchSelectionStrategy,DWriteFontProxy,DirectComposition,DirectCompositionLayers,WidgetLayering --disable-direct-composition-video-overlays --disable-accelerated-2d-canvas --disable-accelerated-video-decode"

    if [ -f "${TARGET_EXE}" ]; then
        (
            sleep 4
            [ -n "$WV2_DIR" ] && export WEBVIEW2_BROWSER_EXECUTABLE_FOLDER="${WV2_DIR}"
            export WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="${WV2_FLAGS}"
            if [ -n "${PROTON_BIN:-}" ] && [ -x "${PROTON_BIN}" ]; then
                "${PROTON_BIN}" run "${TARGET_EXE}" ${TARGET_ARG:+"$TARGET_ARG"} >/dev/null 2>&1 &
            elif [ -n "${STEAM_COMPAT_TOOL_PATHS:-}" ]; then
                PROTON_TOOL=$(echo "${STEAM_COMPAT_TOOL_PATHS}" | tr ':' '\n' | head -n 1)
                if [ -f "${PROTON_TOOL}/proton" ]; then
                    "${PROTON_TOOL}/proton" run "${TARGET_EXE}" ${TARGET_ARG:+"$TARGET_ARG"} >/dev/null 2>&1 &
                fi
            fi
        ) &
    fi
fi

exec "$@"
