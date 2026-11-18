#!/usr/bin/env bash
# common.sh - Shared routines for OK-WuWa Linux launcher, setup, and Steam wrapper

APP_ID="${OKWW_APP_ID:-3513350}"
SHARE_DIR="${OKWW_SHARE_DIR:-${HOME}/.local/share/ok-wuwa}"
APP_ROOT="${OKWW_APP_ROOT:-${SHARE_DIR}/app}"
PYTHON_STANDALONE_URL="https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.zip"
OKWW_UPDATE_REPO="https://github.com/ok-oldking/ok-ww-update.git"

okww_find_resource_dir() {
    local script_dir="$1"
    RESOURCE_DIR=""
    for cand in "${script_dir}" "${SHARE_DIR}"; do
        if [ -n "$cand" ] && [ -f "${cand}/patch_wine_compat.py" ] && [ -f "${cand}/common.sh" ]; then
            RESOURCE_DIR="$(cd "$cand" && pwd)"
            return 0
        fi
    done
    return 1
}

steam_discover_libs() {
    local vdf_candidates=(
        "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/libraryfolders.vdf"
        "${HOME}/.var/app/com.valvesoftware.Steam/data/Steam/steamapps/libraryfolders.vdf"
        "${HOME}/.local/share/Steam/steamapps/libraryfolders.vdf"
        "${HOME}/.steam/steam/steamapps/libraryfolders.vdf"
        "${HOME}/.steam/root/steamapps/libraryfolders.vdf"
    )

    STEAM_LIBS=()
    local seen=()
    local vdf line lib_path real_lib already
    for vdf in "${vdf_candidates[@]}"; do
        [ -f "$vdf" ] || continue
        while IFS= read -r line; do
            if [[ "$line" =~ \"path\"[[:space:]]+\"([^\"]+)\" ]]; then
                lib_path="${BASH_REMATCH[1]}"
                if [ -d "$lib_path" ]; then
                    real_lib="$(readlink -f "$lib_path" 2>/dev/null || printf '%s' "$lib_path")"
                    already=false
                    for s in "${seen[@]}"; do
                        [ "$s" = "$real_lib" ] && { already=true; break; }
                    done
                    if [ "$already" = false ]; then
                        seen+=("$real_lib")
                        STEAM_LIBS+=("$lib_path")
                    fi
                fi
            fi
        done < "$vdf"
    done
}

steam_find_prefix() {
    local explicit="${1:-${OKWW_PREFIX:-${STEAM_COMPAT_DATA_PATH:-}}}"
    PFX_PATH=""
    COMPAT_DATA_PATH=""

    if [ -n "$explicit" ]; then
        if [ -d "${explicit}/pfx" ]; then
            COMPAT_DATA_PATH="$(cd "$explicit" && pwd)"
        elif [ "$(basename "$explicit")" = "pfx" ] && [ -d "$explicit" ]; then
            COMPAT_DATA_PATH="$(dirname "$(cd "$explicit" && pwd)")"
        else
            return 1
        fi
        # Map alternate Btrfs/bind mountpoints (e.g. /var/@ldata -> /var/mnt/LData)
        # to the canonical Steam library path exposed inside Flatpak/pressure-vessel.
        local exp_id exp_stat lib cand_compat
        exp_id="$(basename "${COMPAT_DATA_PATH}")"
        exp_stat="$(stat -c '%d:%i' "${COMPAT_DATA_PATH}" 2>/dev/null || true)"
        if [ -n "$exp_stat" ]; then
            for lib in "${STEAM_LIBS[@]}"; do
                cand_compat="${lib}/steamapps/compatdata/${exp_id}"
                if [ -d "$cand_compat" ] && [ "$(stat -c '%d:%i' "$cand_compat" 2>/dev/null || true)" = "$exp_stat" ]; then
                    COMPAT_DATA_PATH="$cand_compat"
                    break
                fi
            done
        fi
        PFX_PATH="${COMPAT_DATA_PATH}/pfx"
        return 0
    fi

    local lib cand
    for lib in "${STEAM_LIBS[@]}"; do
        cand="${lib}/steamapps/compatdata/${APP_ID}/pfx"
        if [ -d "$cand" ]; then
            PFX_PATH="$cand"
            COMPAT_DATA_PATH="$(dirname "$PFX_PATH")"
            return 0
        fi
    done

    local search_roots=()
    local root
    for root in "/var/mnt" "/mnt" "/media" "/run/media/${USER}" "${HOME}"; do
        [ -d "$root" ] && search_roots+=("$root")
    done
    if [ ${#search_roots[@]} -gt 0 ]; then
        cand=$(find "${search_roots[@]}" -maxdepth 5 -path "*/steamapps/compatdata/${APP_ID}/pfx" -type d 2>/dev/null | head -n 1 || true)
        if [ -n "$cand" ] && [ -d "$cand" ]; then
            PFX_PATH="$cand"
            COMPAT_DATA_PATH="$(dirname "$PFX_PATH")"
            return 0
        fi
    fi

    return 1
}

steam_check_flatpak() {
    IS_FLATPAK=false
    STEAM_CLIENT_PATH="${HOME}/.local/share/Steam"
    if [ -d "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam" ] || \
       (command -v flatpak >/dev/null 2>&1 && flatpak info com.valvesoftware.Steam >/dev/null 2>&1); then
        if [ ! -e "/.flatpak-info" ]; then
            IS_FLATPAK=true
        fi
        STEAM_CLIENT_PATH="${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam"
    fi
}

steam_find_entry_point() {
    if [ -n "${ENTRY_POINT:-}" ] && [ -x "${ENTRY_POINT}" ]; then
        return 0
    fi
    ENTRY_POINT=""
    local root cand

    for root in "${STEAM_LIBS[@]}"; do
        [ -d "${root}/steamapps/common" ] || continue
        cand=$(find "${root}/steamapps/common" -maxdepth 3 -name "_v2-entry-point" -type f -perm -111 2>/dev/null | sort -V | tail -n 1 || true)
        [ -n "$cand" ] && { ENTRY_POINT="$cand"; return 0; }
    done

    for root in "${HOME}/.var/app/com.valvesoftware.Steam/data/Steam" \
                "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam" \
                "${HOME}/.steam/root" "${HOME}/.local/share/Steam"; do
        [ -d "$root" ] || continue
        cand=$(find "${root}" -path "*/steamrt64/pv-runtime/*" -maxdepth 8 -name "_v2-entry-point" -type f -perm -111 2>/dev/null | sort -V | tail -n 1 || true)
        [ -n "$cand" ] && { ENTRY_POINT="$cand"; return 0; }
    done
    return 1
}

steam_find_proton() {
    if [ -n "${PROTON_BIN:-}" ] && [ -x "${PROTON_BIN}" ]; then
        return 0
    fi
    PROTON_BIN=""

    # 1. Steam's explicit tool path when running inside launch options
    if [ -n "${STEAM_COMPAT_TOOL_PATHS:-}" ]; then
        local tool_dir
        while IFS= read -r tool_dir; do
            if [ -n "$tool_dir" ] && [ -x "${tool_dir}/proton" ]; then
                PROTON_BIN="${tool_dir}/proton"
                return 0
            fi
        done < <(printf '%s' "${STEAM_COMPAT_TOOL_PATHS}" | tr ':' '\n')
    fi

    # 2. Exact Proton runner recorded in compatdata/<appid>/config_info
    if [ -n "${COMPAT_DATA_PATH:-}" ] && [ -f "${COMPAT_DATA_PATH}/config_info" ]; then
        local cfg_line walk
        while IFS= read -r cfg_line; do
            case "$cfg_line" in
                /*)
                    walk="$cfg_line"
                    for _ in 1 2 3 4 5; do
                        walk="$(dirname "$walk")"
                        [ "$walk" = "/" ] && break
                        if [ -x "${walk}/proton" ]; then
                            PROTON_BIN="${walk}/proton"
                            return 0
                        fi
                    done
                    ;;
            esac
        done < "${COMPAT_DATA_PATH}/config_info"
    fi

    # 3. Compatibility tools & Steam libraries fallback scan
    local search_dirs=(
        "${HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d"
        "${HOME}/.var/app/com.valvesoftware.Steam/data/Steam/compatibilitytools.d"
        "${HOME}/.local/share/Steam/compatibilitytools.d"
        "${HOME}/.steam/root/compatibilitytools.d"
    )
    local lib
    for lib in "${STEAM_LIBS[@]}"; do
        search_dirs+=("${lib}/compatibilitytools.d" "${lib}/steamapps/common")
    done

    local dir cand
    for dir in "${search_dirs[@]}"; do
        [ -d "$dir" ] || continue
        cand=$(find "$dir" -maxdepth 3 -name "proton" -type f -perm -111 2>/dev/null | grep -E "DW-Proton|Proton-CachyOS|GE-Proton|Proton - Experimental|Proton [0-9]" | sort -V | tail -n 1 || true)
        [ -n "$cand" ] && [ -x "$cand" ] && { PROTON_BIN="$cand"; return 0; }
    done

    for dir in "${search_dirs[@]}"; do
        [ -d "$dir" ] || continue
        cand=$(find "$dir" -maxdepth 3 -name "proton" -type f -perm -111 2>/dev/null | head -n 1 || true)
        [ -n "$cand" ] && [ -x "$cand" ] && { PROTON_BIN="$cand"; return 0; }
    done

    return 1
}

okww_to_win_z() {
    printf 'Z:%s' "$1" | sed 's|/|\\|g'
}

okww_resolve_app_paths() {
    DATA_APP_DIR="${APP_ROOT}/data/apps/ok-ww"
    PYTHON_HOST="${DATA_APP_DIR}/python/python.exe"
    REPO_HOST="${DATA_APP_DIR}/repo"
    WORKING_HOST="${DATA_APP_DIR}/working"
    MAIN_PY_HOST="${WORKING_HOST}/main.py"

    # Legacy fallback if installed inside prefix prior to zero-pollution layout
    if [ ! -f "${MAIN_PY_HOST}" ] && [ -n "${PFX_PATH:-}" ] && [ -d "${PFX_PATH}/drive_c/users/steamuser/AppData/Local/ok-ww/data/apps/ok-ww/working" ]; then
        DATA_APP_DIR="${PFX_PATH}/drive_c/users/steamuser/AppData/Local/ok-ww/data/apps/ok-ww"
        PYTHON_HOST="${DATA_APP_DIR}/python/python.exe"
        REPO_HOST="${DATA_APP_DIR}/repo"
        WORKING_HOST="${DATA_APP_DIR}/working"
        MAIN_PY_HOST="${WORKING_HOST}/main.py"
    fi

    PYTHON_WIN="$(okww_to_win_z "${PYTHON_HOST}")"
    WORKING_WIN="$(okww_to_win_z "${WORKING_HOST}")"
    MAIN_PY_WIN="$(okww_to_win_z "${MAIN_PY_HOST}")"
}

okww_apply_patches() {
    if [ -d "${WORKING_HOST}" ] && [ -n "${RESOURCE_DIR:-}" ] && [ -f "${RESOURCE_DIR}/patch_wine_compat.py" ]; then
        python3 "${RESOURCE_DIR}/patch_wine_compat.py" "${WORKING_HOST}" --prefix "${PFX_PATH:-}" --offline >/dev/null 2>&1 || \
        python3 "${RESOURCE_DIR}/patch_wine_compat.py" "${WORKING_HOST}" --prefix "${PFX_PATH:-}" >/dev/null 2>&1 || true
    fi
}

okww_same_dir() {
    local a="$1" b="$2"
    [ -d "$a" ] && [ -d "$b" ] || return 1
    [ "$(stat -c '%d:%i' "$a" 2>/dev/null)" = "$(stat -c '%d:%i' "$b" 2>/dev/null)" ]
}

okww_proc_matches_prefix() {
    local pid="$1"
    local target_pfx="$2"
    [ -r "/proc/${pid}/environ" ] || return 1
    local env_pfx env_compat
    env_pfx=$(tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null | sed -n 's/^WINEPREFIX=//p' | head -n 1)
    if [ -n "$env_pfx" ] && okww_same_dir "$env_pfx" "$target_pfx"; then
        return 0
    fi
    env_compat=$(tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null | sed -n 's/^STEAM_COMPAT_DATA_PATH=//p' | head -n 1)
    if [ -n "$env_compat" ] && okww_same_dir "${env_compat}/pfx" "$target_pfx"; then
        return 0
    fi
    return 1
}

okww_find_game_pid() {
    GAME_PID=""
    [ -n "${PFX_PATH:-}" ] || return 1
    local pfx_real pid
    pfx_real="$(readlink -f "${PFX_PATH}" 2>/dev/null || printf '%s' "${PFX_PATH}")"

    # Prefer the live game binary when running
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        if okww_proc_matches_prefix "$pid" "$pfx_real"; then
            GAME_PID="$pid"
            return 0
        fi
    done < <(pgrep -f "Client-Win64-Shipping\.exe" 2>/dev/null || true)

    return 1
}

okww_find_prefix_wineserver_pid() {
    WS_PID=""
    [ -n "${PFX_PATH:-}" ] || return 1
    local pfx_real pid
    pfx_real="$(readlink -f "${PFX_PATH}" 2>/dev/null || printf '%s' "${PFX_PATH}")"

    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        if okww_proc_matches_prefix "$pid" "$pfx_real"; then
            WS_PID="$pid"
            return 0
        fi
    done < <(pgrep -x "wineserver" 2>/dev/null || true)

    return 1
}

okww_is_app_running_in_prefix() {
    [ -n "${PFX_PATH:-}" ] || return 1
    local pfx_real pid
    pfx_real="$(readlink -f "${PFX_PATH}" 2>/dev/null || printf '%s' "${PFX_PATH}")"
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        [ "$pid" = "$$" ] && continue
        if okww_proc_matches_prefix "$pid" "$pfx_real"; then
            return 0
        fi
    done < <(pgrep -f "ok-ww.*main\.py" 2>/dev/null || true)
    return 1
}

okww_run_in_fresh_container() {
    local compat_real
    compat_real="$(readlink -f "${COMPAT_DATA_PATH}" 2>/dev/null || printf '%s' "${COMPAT_DATA_PATH}")"

    if [ "${IS_FLATPAK}" = true ] && [ -n "${ENTRY_POINT:-}" ] && command -v flatpak >/dev/null 2>&1; then
        local fpk_env=(
            --env=STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}"
            --env=STEAM_COMPAT_DATA_PATH="${compat_real}"
            --env=PYTHONIOENCODING=utf-8
            --env=OKWW_HANDOFF_FILE="${OKWW_HANDOFF_FILE:-}"
            --env=OKWW_AUTO_START="${OKWW_AUTO_START:-}"
        )
        [ -n "${PIP_CACHE_DIR:-}" ] && fpk_env+=(--env=PIP_CACHE_DIR="${PIP_CACHE_DIR}")
        flatpak run \
            "${fpk_env[@]}" \
            --command="${ENTRY_POINT}" \
            com.valvesoftware.Steam \
            --verb=runinprefix -- "$@"
        return $?
    fi

    export STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}"
    export STEAM_COMPAT_DATA_PATH="${compat_real}"
    export PYTHONIOENCODING=utf-8
    if [ -n "${ENTRY_POINT:-}" ]; then
        "${ENTRY_POINT}" --verb=runinprefix -- "$@"
        return $?
    fi
    "$@"
}

okww_join_container_by_pid() {
    local target_pid="$1"
    shift
    local compat_real
    compat_real="$(readlink -f "${COMPAT_DATA_PATH}" 2>/dev/null || printf '%s' "${COMPAT_DATA_PATH}")"

    # 1. Inside the container already (e.g. steam-wrapper.sh)
    if [ -r "/proc/${target_pid}/ns/mnt" ] && [ -r "/proc/$$/ns/mnt" ] && \
       [ "$(readlink "/proc/${target_pid}/ns/mnt")" = "$(readlink "/proc/$$/ns/mnt")" ]; then
        env \
            STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}" \
            STEAM_COMPAT_DATA_PATH="${compat_real}" \
            PYTHONIOENCODING=utf-8 \
            OKWW_AUTO_START="${OKWW_AUTO_START:-}" \
            "$@"
        return $?
    fi

    # 2. Flatpak subsandbox join (works without Launch Options or root!)
    if command -v flatpak >/dev/null 2>&1 && flatpak enter "${target_pid}" true >/dev/null 2>&1; then
        flatpak enter "${target_pid}" env \
            STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}" \
            STEAM_COMPAT_DATA_PATH="${compat_real}" \
            PYTHONIOENCODING=utf-8 \
            OKWW_AUTO_START="${OKWW_AUTO_START:-}" \
            "$@"
        return $?
    fi

    # 3. Native Linux bwrap user-namespace join
    if command -v nsenter >/dev/null 2>&1 && nsenter -U --preserve-credentials -m -i -p -t "${target_pid}" true >/dev/null 2>&1; then
        nsenter -U --preserve-credentials -m -i -p -t "${target_pid}" env \
            STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}" \
            STEAM_COMPAT_DATA_PATH="${compat_real}" \
            PYTHONIOENCODING=utf-8 \
            OKWW_AUTO_START="${OKWW_AUTO_START:-}" \
            "$@"
        return $?
    fi

    # 4. Pressure-vessel D-Bus launcher-service fallback
    if [ -n "${ENTRY_POINT:-}" ]; then
        local lc="$(dirname "${ENTRY_POINT}")/pressure-vessel/bin/steam-runtime-launch-client"
        if [ -x "$lc" ]; then
            "$lc" --inside-app="${APP_ID}" -- env \
                STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}" \
                STEAM_COMPAT_DATA_PATH="${compat_real}" \
                PYTHONIOENCODING=utf-8 \
                OKWW_AUTO_START="${OKWW_AUTO_START:-}" \
                "$@"
            return $?
        fi
    fi

    return 1
}

okww_trigger_steam_game() {
    local steam_uri="${1:-steam://rungameid/${APP_ID}}"
    if [ "${IS_FLATPAK}" = true ] && command -v flatpak >/dev/null 2>&1; then
        if flatpak ps --columns=application 2>/dev/null | grep -qx "com.valvesoftware.Steam"; then
            nohup flatpak run com.valvesoftware.Steam "${steam_uri}" >/dev/null 2>&1 &
            return 0
        fi
    fi
    if command -v xdg-open >/dev/null 2>&1; then
        nohup xdg-open "${steam_uri}" >/dev/null 2>&1 &
        return 0
    fi
    if command -v steam >/dev/null 2>&1; then
        nohup steam "${steam_uri}" >/dev/null 2>&1 &
        return 0
    fi
    return 1
}

okww_bootstrap_or_update() {
    local requested_tag="${1:-}"
    okww_resolve_app_paths
    mkdir -p "${DATA_APP_DIR}/python" "${APP_ROOT}/cache/pip" "${SHARE_DIR}/run"

    # 1. Ensure Flatpak Steam has read-write access to ~/.local/share/ok-wuwa
    if [ "${IS_FLATPAK}" = true ] && command -v flatpak >/dev/null 2>&1; then
        flatpak override --user --filesystem="${SHARE_DIR}:rw" com.valvesoftware.Steam 2>/dev/null || true
    fi

    # 2. Bootstrap Windows Python 3.12 standalone if missing
    if [ ! -f "${PYTHON_HOST}" ]; then
        echo "  -> Downloading standalone Windows Python 3.12..."
        local py_zip
        py_zip="$(mktemp --suffix=.zip)"
        curl -fL --retry 3 -o "${py_zip}" "${PYTHON_STANDALONE_URL}"
        python3 -m zipfile -e "${py_zip}" "${DATA_APP_DIR}/python"
        rm -f "${py_zip}"
    fi

    # 3. Clone or fetch bare ok-ww-update repository
    if [ ! -d "${REPO_HOST}/objects" ]; then
        echo "  -> Cloning OK-WW release repository..."
        rm -rf "${REPO_HOST}"
        git clone --bare --filter=blob:none "${OKWW_UPDATE_REPO}" "${REPO_HOST}"
    else
        echo "  -> Fetching latest OK-WW tags..."
        git --git-dir="${REPO_HOST}" fetch --tags --force origin 2>/dev/null || echo "  -> Offline: using cached git tags."
    fi

    local target_tag="${requested_tag}"
    if [ -z "${target_tag}" ]; then
        target_tag=$(git --git-dir="${REPO_HOST}" tag -l | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1)
    fi
    if [ -z "${target_tag}" ]; then
        echo "Error: Could not resolve an OK-WW release tag." >&2
        return 1
    fi

    mkdir -p "${WORKING_HOST}"
    echo "  -> Checking out OK-WW ${target_tag}..."
    git --git-dir="${REPO_HOST}" --work-tree="${WORKING_HOST}" checkout -q -f "${target_tag}"

    # 4. Sync Python wheel dependencies only when requirements.txt changes
    local req_file="${WORKING_HOST}/requirements.txt"
    local stamp_file="${DATA_APP_DIR}/python/.requirements.sha256"
    if [ -f "${req_file}" ]; then
        local cur_hash old_hash=""
        cur_hash="$(sha256sum "${req_file}" | awk '{print $1}')"
        [ -f "${stamp_file}" ] && old_hash="$(cat "${stamp_file}" 2>/dev/null || true)"
        if [ "${cur_hash}" != "${old_hash}" ] || [ ! -d "${DATA_APP_DIR}/python/Lib/site-packages/PySide6" ]; then
            echo "  -> Installing Windows Python dependencies for ${target_tag}..."
            local req_win cache_win
            req_win="$(okww_to_win_z "${req_file}")"
            cache_win="$(okww_to_win_z "${APP_ROOT}/cache/pip")"
            PIP_CACHE_DIR="${cache_win}" okww_run_in_fresh_container \
                "${PROTON_BIN}" runinprefix "${PYTHON_WIN}" -m pip install \
                --no-deps --prefer-binary --no-warn-script-location -r "${req_win}"
            printf '%s\n' "${cur_hash}" > "${stamp_file}"
        else
            echo "  -> Python dependencies already up to date."
        fi
    fi

    # 5. Apply Wine/Proton compatibility patches
    if [ -n "${RESOURCE_DIR:-}" ] && [ -f "${RESOURCE_DIR}/patch_wine_compat.py" ]; then
        python3 "${RESOURCE_DIR}/patch_wine_compat.py" "${WORKING_HOST}" --prefix "${PFX_PATH}" --offline
    fi
}
