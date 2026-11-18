#!/usr/bin/env bash
# steam-wrapper.sh - Optional 1-Click Steam Launch Option Companion for OK-WuWa
# Usage in Steam -> Wuthering Waves -> Properties -> Launch Options:
#   ~/.local/share/ok-wuwa/steam-wrapper.sh %command%

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "${SCRIPT_DIR}/common.sh" ]; then
    source "${SCRIPT_DIR}/common.sh"
elif [ -f "${HOME}/.local/share/ok-wuwa/common.sh" ]; then
    source "${HOME}/.local/share/ok-wuwa/common.sh"
else
    exec "$@"
fi

okww_find_resource_dir "${SCRIPT_DIR}" || true
steam_discover_libs
steam_check_flatpak

if ! steam_find_prefix; then
    exec "$@"
fi

# Preserve Steam's per-game environment when invoked from Steam; only export
# fallback values when testing the wrapper manually outside Steam.
if [ -z "${STEAM_COMPAT_DATA_PATH:-}" ]; then
    export STEAM_COMPAT_DATA_PATH="${COMPAT_DATA_PATH}"
fi
if [ -z "${STEAM_COMPAT_CLIENT_INSTALL_PATH:-}" ]; then
    export STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}"
fi

steam_find_proton || true
okww_resolve_app_paths
okww_apply_patches

# Steam runs Launch Options inside the game's pressure-vessel container, so
# launching via `proton runinprefix` directly shares the game's /tmp and
# wineserver automatically. Delay until Client-Win64-Shipping.exe exists so
# the game's initial `proton waitforexitandrun` (`wineserver -w`) never blocks.
if [ -n "${PROTON_BIN:-}" ] && [ -f "${PYTHON_HOST}" ] && [ -f "${MAIN_PY_HOST}" ]; then
    (
        for _ in $(seq 1 180); do
            pgrep -f "Client-Win64-Shipping\.exe" >/dev/null 2>&1 && break
            sleep 1
        done
        if pgrep -f "Client-Win64-Shipping\.exe" >/dev/null 2>&1 && ! okww_is_app_running_in_prefix; then
            cd "${WORKING_HOST}" || exit 0
            export PYTHONIOENCODING=utf-8
            "${PROTON_BIN}" runinprefix "${PYTHON_WIN}" "${MAIN_PY_WIN}" >/dev/null 2>&1 &
        fi
    ) &
fi

exec "$@"
