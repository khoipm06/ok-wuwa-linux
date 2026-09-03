#!/usr/bin/env bash
# common.sh - Shared routines for OK-WuWa Linux runner & wrappers

APP_ID="3513350"

okww_find_resource_dir() {
    local script_dir="$1"
    RESOURCE_DIR=""
    for cand in "${script_dir}" "${HOME}/.local/share/ok-wuwa"; do
        if [ -f "${cand}/webview2_render_fix.py" ] && [ -f "${cand}/cursor_visible.py" ] && [ -f "${cand}/patch_wine_compat.py" ]; then
            RESOURCE_DIR="${cand}"
            break
        fi
    done
}

steam_discover_libs() {
    local vdf_candidates=(
        "${HOME}/.steam/steam/steamapps/libraryfolders.vdf"
        "${HOME}/.steam/root/steamapps/libraryfolders.vdf"
        "${HOME}/.local/share/Steam/steamapps/libraryfolders.vdf"
        "${HOME}/.var/app/com.valvesoftware.Steam/data/Steam/steamapps/libraryfolders.vdf"
        "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/libraryfolders.vdf"
    )

    STEAM_LIBS=()
    for vdf in "${vdf_candidates[@]}"; do
        if [ -f "$vdf" ]; then
            while IFS= read -r line; do
                if [[ "$line" =~ \"path\"[[:space:]]+\"([^\"]+)\" ]]; then
                    local lib_path="${BASH_REMATCH[1]}"
                    [ -d "$lib_path" ] && STEAM_LIBS+=("$lib_path")
                fi
            done < "$vdf"
        fi
    done

    if [ ${#STEAM_LIBS[@]} -gt 0 ]; then
        readarray -t STEAM_LIBS < <(printf '%s\n' "${STEAM_LIBS[@]}" | sort -u)
    fi
}

steam_find_prefix() {
    PFX_PATH="${STEAM_COMPAT_DATA_PATH:-""}"
    if [ -n "$PFX_PATH" ] && [ -d "${PFX_PATH}/pfx" ]; then
        PFX_PATH="${PFX_PATH}/pfx"
    fi

    if [ -z "$PFX_PATH" ] || [ ! -d "$PFX_PATH" ]; then
        for lib in "${STEAM_LIBS[@]}"; do
            local cand="${lib}/steamapps/compatdata/${APP_ID}/pfx"
            [ -d "$cand" ] && { PFX_PATH="$cand"; break; }
        done
    fi

    if [ -z "$PFX_PATH" ] || [ ! -d "$PFX_PATH" ]; then
        local search_roots=()
        for root in "/var/mnt" "/mnt" "/media" "/run/media/${USER}" "${HOME}"; do
            [ -d "$root" ] && search_roots+=("$root")
        done
        if [ ${#search_roots[@]} -gt 0 ]; then
            PFX_PATH=$(find "${search_roots[@]}" -maxdepth 5 -path "*/steamapps/compatdata/${APP_ID}/pfx" -type d 2>/dev/null | head -n 1 || true)
        fi
    fi

    if [ -n "$PFX_PATH" ] && [ -d "$PFX_PATH" ]; then
        COMPAT_DATA_PATH="$(dirname "${PFX_PATH}")"
        return 0
    fi
    return 1
}

steam_find_entry_point() {
    ENTRY_POINT=""
    for lib in "${STEAM_LIBS[@]}"; do
        local cand
        cand=$(find "${lib}/steamapps/common" -maxdepth 3 -name "_v2-entry-point" -type f -perm -111 2>/dev/null | sort -V | tail -n 1 || true)
        [ -n "$cand" ] && { ENTRY_POINT="$cand"; return 0; }
    done
    return 1
}

steam_find_proton() {
    PROTON_BIN="${PROTON_BIN:-}"
    if [ -n "$PROTON_BIN" ] && [ -x "$PROTON_BIN" ]; then
        return 0
    fi

    local search_dirs=()
    if [ -n "${STEAM_COMPAT_TOOL_PATHS:-}" ]; then
        while IFS= read -r tool_dir; do
            [ -d "$tool_dir" ] && search_dirs+=("$tool_dir" "${tool_dir}/files")
        done < <(echo "${STEAM_COMPAT_TOOL_PATHS}" | tr ':' '\n')
    fi

    search_dirs+=(
        "${HOME}/.steam/root/compatibilitytools.d"
        "${HOME}/.local/share/Steam/compatibilitytools.d"
        "${HOME}/.var/app/com.valvesoftware.Steam/data/Steam/compatibilitytools.d"
        "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d"
    )
    for lib in "${STEAM_LIBS[@]}"; do
        search_dirs+=("${lib}/compatibilitytools.d" "${lib}/steamapps/common")
    done

    for dir in "${search_dirs[@]}"; do
        if [ -d "$dir" ]; then
            local cand
            cand=$(find "$dir" -maxdepth 3 -name "proton" -type f -perm -111 2>/dev/null | grep -E "Proton-CachyOS|GE-Proton|Proton - Experimental|Proton [0-9]" | head -n 1 || true)
            [ -n "$cand" ] && [ -x "$cand" ] && { PROTON_BIN="$cand"; return 0; }
        fi
    done

    for dir in "${search_dirs[@]}"; do
        if [ -d "$dir" ]; then
            local cand
            cand=$(find "$dir" -maxdepth 3 -name "proton" -type f -perm -111 2>/dev/null | head -n 1 || true)
            [ -n "$cand" ] && [ -x "$cand" ] && { PROTON_BIN="$cand"; return 0; }
        fi
    done

    return 1
}

steam_check_flatpak() {
    IS_FLATPAK=false
    STEAM_CLIENT_PATH="${HOME}/.local/share/Steam"
    if [ -d "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam" ] || (command -v flatpak >/dev/null 2>&1 && flatpak info com.valvesoftware.Steam >/dev/null 2>&1); then
        IS_FLATPAK=true
        STEAM_CLIENT_PATH="${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam"
    fi
}

okww_find_app_dir() {
    APP_DIR=""
    PFX_USER="steamuser"

    if [ -n "$PFX_PATH" ] && [ -d "${PFX_PATH}/drive_c/users" ]; then
        for u_dir in "${PFX_PATH}/drive_c/users"/*; do
            local cand="${u_dir}/AppData/Local/ok-ww"
            if [ -d "$cand" ]; then
                APP_DIR="$cand"
                PFX_USER="$(basename "$u_dir")"
                break
            fi
        done
    fi

    if [ -z "$APP_DIR" ]; then
        APP_DIR="${PFX_PATH}/drive_c/users/steamuser/AppData/Local/ok-ww"
        PFX_USER="steamuser"
    fi

    WORKING_DIR="${APP_DIR}/data/apps/ok-ww/working"
}

okww_resolve_targets() {
    # The Tauri launcher shell (ok-ww.exe) needs WebView2, which fails to
    # create inside the nested flatpak->bwrap sandbox (0x80010108). Default
    # to the python entry point, which the automation UI needs anyway.
    LAUNCHER_WIN="C:\\users\\${PFX_USER}\\AppData\\Local\\ok-ww\\ok-ww.exe"
    PYTHON_WIN="C:\\users\\${PFX_USER}\\AppData\\Local\\ok-ww\\data\\apps\\ok-ww\\python\\python.exe"
    MAIN_PY_WIN="C:\\users\\${PFX_USER}\\AppData\\Local\\ok-ww\\data\\apps\\ok-ww\\working\\main.py"

    TARGET_EXE="${PYTHON_WIN}"
    TARGET_ARG="${MAIN_PY_WIN}"

    if [ "$1" = "--launcher" ] && [ -f "${APP_DIR}/ok-ww.exe" ]; then
        TARGET_EXE="${LAUNCHER_WIN}"
        TARGET_ARG=""
        shift
    fi
}

okww_detect_wv2() {
    WV2_DIR=""
    if [ -z "$PFX_PATH" ] || [ ! -d "$PFX_PATH" ]; then
        return 1
    fi

    for check_path in "${PFX_PATH}/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application" "${PFX_PATH}/drive_c/Program Files/Microsoft/EdgeWebView/Application"; do
        if [ -d "$check_path" ]; then
            for v_dir in "$check_path"/*; do
                if [ -d "$v_dir" ] && [ -f "${v_dir}/msedgewebview2.exe" ]; then
                    local v_name
                    v_name="$(basename "$v_dir")"
                    WV2_DIR="C:\\Program Files (x86)\\Microsoft\\EdgeWebView\\Application\\${v_name}"
                    return 0
                fi
            done
        fi
    done
    return 1
}

okww_get_render_fix_win() {
    RENDER_FIX_WIN=""
    if [ "${TARGET_EXE}" = "${LAUNCHER_WIN}" ]; then
        if [ -n "$RESOURCE_DIR" ] && [ -f "${RESOURCE_DIR}/webview2_render_fix.py" ]; then
            RENDER_FIX_WIN="Z:$(printf '%s' "${RESOURCE_DIR}/webview2_render_fix.py" | sed 's|/|\\|g')"
        fi
    fi
}

okww_wv2_flags() {
    # Chromium sandbox/GPU paths break inside the bwrap/pressure-vessel
    # sandbox; WebView2 fails to create (0x80010108) without these switches.
    WV2_FLAGS="--no-sandbox --disable-gpu --disable-gpu-compositing --disable-gpu-rasterization --in-process-gpu --disable-features=RendererCodeIntegrity,TouchEvents,TouchSelectionStrategy,DWriteFontProxy,DirectComposition,DirectCompositionLayers,WidgetLayering --disable-direct-composition-video-overlays --disable-accelerated-2d-canvas --disable-accelerated-video-decode"
}

okww_launch_app() {
    # The app must join the same bwrap/pressure-vessel /tmp tmpfs as the
    # Steam-launched game, otherwise Wine rendezvous via a second isolated
    # wineserver (window enumeration and steam:// launching both break).
    # Going through `flatpak run` of the Steam app shares that tmpfs.
    export STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}"
    export STEAM_COMPAT_DATA_PATH="${COMPAT_DATA_PATH}"
    export OKWW_APP_VERSION="${APP_VERSION}"
    export OKWW_APP_EXE="${APP_EXE_WIN}"

    if [ "${IS_FLATPAK}" = true ] && [ -n "${ENTRY_POINT}" ] && command -v flatpak >/dev/null 2>&1; then
        exec flatpak run \
            --env=STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}" \
            --env=STEAM_COMPAT_DATA_PATH="${COMPAT_DATA_PATH}" \
            --env=OKWW_PROTON="${PROTON_BIN}" \
            --env=OKWW_TARGET="${TARGET_EXE}" \
            --env=OKWW_PYTHON="${PYTHON_WIN}" \
            --env=OKWW_FIX="${RENDER_FIX_WIN}" \
            --env=OKWW_ARGS="${TARGET_ARG:+${TARGET_ARG} }$*" \
            --env=OKWW_APP_VERSION="${APP_VERSION}" \
            --env=OKWW_APP_EXE="${APP_EXE_WIN}" \
            --command="${ENTRY_POINT}" \
            com.valvesoftware.Steam \
            --verb=runinprefix -- bash -c "$INNER"
    fi

    if [ -n "${ENTRY_POINT}" ]; then
        [ -n "$WV2_DIR" ] && export WEBVIEW2_BROWSER_EXECUTABLE_FOLDER="${WV2_DIR}"
        exec "${ENTRY_POINT}" --verb=runinprefix -- bash -c "$INNER"
    fi
    exec bash -c "$INNER"
}

okww_start_cursor_fix() {
    if [ -n "$RESOURCE_DIR" ] && [ -f "${RESOURCE_DIR}/cursor_visible.py" ]; then
        ( python3 "${RESOURCE_DIR}/cursor_visible.py" >/dev/null 2>&1 & ) 2>/dev/null || true
    fi
}

okww_apply_patches() {
    if [ -d "${WORKING_DIR}" ] && [ -n "$RESOURCE_DIR" ] && [ -f "${RESOURCE_DIR}/patch_wine_compat.py" ]; then
        python3 "${RESOURCE_DIR}/patch_wine_compat.py" "${PFX_PATH}" >/dev/null 2>&1 || true
    fi
}

okww_find_game_shipping() {
    GAME_SHIPPING=""
    [ -z "$PFX_PATH" ] || [ ! -d "$PFX_PATH" ] && return 1

    local search_parts=(
        "common/Wuthering Waves/Client/Binaries/Win64/Client-Win64-Shipping.exe"
        "steamapps/common/Wuthering Waves/Client/Binaries/Win64/Client-Win64-Shipping.exe"
    )
    local dd_dir="${PFX_PATH}/dosdevices"
    [ ! -d "$dd_dir" ] && return 1
    local link letter real target
    for link in "${dd_dir}"/[a-zA-Z]: ; do
        [ -L "$link" ] || continue
        letter="$(basename "$link")"
        real="$(readlink -f "$link")" || continue
        [ -d "$real" ] || continue
        for parts in "${search_parts[@]}"; do
            target="${real}/${parts}"
            if [ -f "$target" ]; then
                GAME_SHIPPING="${letter^}\\$(echo "$parts" | sed 's|/|\\|g')"
                return 0
            fi
        done
    done
    return 1
}

okww_read_app_json() {
    APP_VERSION=""
    APP_PROFILE="Global"
    APP_EXE_WIN=""
    local app_json="${APP_DIR}/data/apps/ok-ww/app.json"
    if [ -f "$app_json" ] && command -v python3 >/dev/null 2>&1; then
        read -r APP_VERSION APP_PROFILE < <(python3 -c "
import json
d = json.load(open(r'$app_json'))
print(d.get('current_version') or '', d.get('current_profile') or 'Global')
" 2>/dev/null) || true
    fi
    [ -f "${APP_DIR}/ok-ww.exe" ] && APP_EXE_WIN="C:\\users\\${PFX_USER}\\AppData\\Local\\ok-ww\\ok-ww.exe"
}

okww_build_inner_cmd() {
    cat << 'EOF'
export PYAPPIFY_APP_VERSION="${OKWW_APP_VERSION}"
export PYAPPIFY_APP_STARTING_VERSION="${OKWW_APP_VERSION}"
export PYAPPIFY_VERSION="1.2.3"
export PYAPPIFY_EXECUTABLE="${OKWW_APP_EXE}"
if [ -z "$OKWW_FIX" ]; then exec "$OKWW_PROTON" runinprefix "$OKWW_TARGET" $OKWW_ARGS; fi
"$OKWW_PROTON" runinprefix "$OKWW_TARGET" $OKWW_ARGS &
"$OKWW_PROTON" runinprefix "$OKWW_PYTHON" "$OKWW_FIX"
wait
EOF
}
