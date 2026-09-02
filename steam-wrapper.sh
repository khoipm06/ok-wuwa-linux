#!/usr/bin/env bash
# Steam Launch Option Companion for OK-WuWa
# Usage (Steam -> Wuthering Waves -> Properties -> Launch Options):
#   ~/.local/share/ok-wuwa/steam-wrapper.sh %command%

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source shared helpers (from this checkout, or the installed share dir)
if [ -f "${SCRIPT_DIR}/common.sh" ]; then
    source "${SCRIPT_DIR}/common.sh"
elif [ -f "${HOME}/.local/share/ok-wuwa/common.sh" ]; then
    source "${HOME}/.local/share/ok-wuwa/common.sh"
else
    echo "Error: common.sh not found. Run setup.sh first." >&2
    exit 1
fi

okww_find_resource_dir "${SCRIPT_DIR}"
steam_discover_libs

# Steam provides STEAM_COMPAT_DATA_PATH; fall back to library scan when the
# wrapper is invoked manually (e.g. testing) without Steam's environment.
if ! steam_find_prefix; then
    exec "$@"
fi

okww_find_app_dir
okww_apply_patches
okww_resolve_targets ""

# Manual invocation only: overwriting Steam's per-game env would break
# the attached game's prefix.
if [ -z "${STEAM_COMPAT_DATA_PATH:-}" ]; then
    steam_check_flatpak
    export STEAM_COMPAT_DATA_PATH="${COMPAT_DATA_PATH}"
    export STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT_PATH}"
fi

# Detect installed WebView2 Runtime path
okww_detect_wv2 || true
okww_get_render_fix_win
okww_wv2_flags
if [ -z "${RENDER_FIX_WIN}" ] && [ "${TARGET_EXE}" = "${LAUNCHER_WIN}" ]; then
    echo "Warning: WebView2 render-fix helper not installed; run setup.sh." >&2
fi

# Proton runner: prefer Steam's tool paths, then compatibilitytools.d scan.
steam_find_proton || true

export OKWW_PROTON="${PROTON_BIN}"
export OKWW_TARGET="${TARGET_EXE}"
export OKWW_PYTHON="${PYTHON_WIN}"
export OKWW_FIX="${RENDER_FIX_WIN}"
export OKWW_ARGS="${TARGET_ARG}"
INNER="$(okww_build_inner_cmd)"

# Host-side cursor watcher: KWin renders no cursor over cursor-less XWayland
# windows; define the theme cursor on the ok-ww window when it appears.
okww_start_cursor_fix

# Launch OK-WuWa alongside the game. Both processes must share one wineserver,
# so the render-fix helper runs in the same process tree (same container).
# If no Proton runner is resolvable, skip silently - the game still launches.
if [ -n "${PROTON_BIN}" ]; then
    if [ -f "${APP_DIR}/ok-ww.exe" ] || { [ -f "${APP_DIR}/data/apps/ok-ww/python/python.exe" ] && [ -f "${APP_DIR}/data/apps/ok-ww/working/main.py" ]; }; then
        (
            [ -n "$WV2_DIR" ] && export WEBVIEW2_BROWSER_EXECUTABLE_FOLDER="${WV2_DIR}"
            export WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="${WV2_FLAGS}"
            bash -c "$INNER" >/dev/null 2>&1 &
        ) &
    fi
fi

exec "$@"
