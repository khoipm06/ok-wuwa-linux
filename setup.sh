#!/usr/bin/env bash
# setup.sh - Automated zero-pollution installer for OK-WuWa on Linux
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

EXPLICIT_PREFIX=""
TARGET_TAG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix)
            EXPLICIT_PREFIX="$2"
            shift 2
            ;;
        --prefix=*)
            EXPLICIT_PREFIX="${1#*=}"
            shift
            ;;
        --version)
            TARGET_TAG="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

echo "=========================================================================="
echo "                        OK-WuWa Linux Auto-Setup                          "
echo "=========================================================================="

# Auto-update repository when running from a clean git checkout with a remote
if [ -d "${SCRIPT_DIR}/.git" ] && command -v git >/dev/null 2>&1; then
    if git -C "${SCRIPT_DIR}" remote -v 2>/dev/null | grep -q "fetch" && \
       [ -z "$(git -C "${SCRIPT_DIR}" status --porcelain 2>/dev/null)" ]; then
        echo "[*] Checking for latest ok-wuwa-linux updates..."
        git -C "${SCRIPT_DIR}" pull --ff-only 2>/dev/null || echo "  -> Offline or non-fast-forward; continuing with local files."
    fi
fi

# 1. Discover Steam libraries
echo "[1/5] Discovering Steam library folders..."
steam_discover_libs
echo "  -> Found ${#STEAM_LIBS[@]} Steam library folder(s)."

# 2. Locate Wuthering Waves Proton prefix
echo "[2/5] Locating Wuthering Waves (App ID: ${APP_ID}) Proton prefix..."
if ! steam_find_prefix "${EXPLICIT_PREFIX}"; then
    echo "Error: Proton prefix for Wuthering Waves (${APP_ID}) not found." >&2
    echo "Launch Wuthering Waves once in Steam before running ./setup.sh." >&2
    exit 1
fi
echo "  -> Prefix: ${PFX_PATH} (zero-pollution mode: game prefix will not be modified)"

# 3. Detect Proton runner & Steam Runtime container
echo "[3/5] Detecting matching Proton runner & container runtime..."
steam_check_flatpak
steam_find_entry_point || true
if ! steam_find_proton; then
    echo "Error: No usable Proton executable found." >&2
    exit 1
fi
echo "  -> Proton: ${PROTON_BIN}"

# 4. Install launcher helpers to XDG directories first so resource lookup succeeds
echo "[4/5] Installing launcher scripts & XDG desktop integration..."
mkdir -p \
    "${HOME}/.local/bin" \
    "${HOME}/.local/share/applications" \
    "${HOME}/.local/share/icons/hicolor/256x256/apps" \
    "${SHARE_DIR}"

cp "${SCRIPT_DIR}/common.sh" "${SHARE_DIR}/common.sh"
cp "${SCRIPT_DIR}/patch_wine_compat.py" "${SHARE_DIR}/patch_wine_compat.py"
cp "${SCRIPT_DIR}/steam-wrapper.sh" "${SHARE_DIR}/steam-wrapper.sh"
cp "${SCRIPT_DIR}/ok-wuwa" "${HOME}/.local/bin/ok-wuwa"
chmod +x "${SHARE_DIR}/patch_wine_compat.py" "${SHARE_DIR}/steam-wrapper.sh" "${HOME}/.local/bin/ok-wuwa"

okww_find_resource_dir "${SHARE_DIR}"

if [ "${IS_FLATPAK}" = true ] && command -v flatpak >/dev/null 2>&1; then
    echo "  -> Granting Flatpak Steam access to ${SHARE_DIR}..."
    flatpak override --user --filesystem="${SHARE_DIR}:rw" com.valvesoftware.Steam 2>/dev/null || true
fi

# 5. Bootstrap / update OK-WW payload in ~/.local/share/ok-wuwa/app and apply Wine patches
echo "[5/5] Bootstrapping OK-WW payload & applying Wine compatibility patches..."
okww_bootstrap_or_update "${TARGET_TAG}"

ICON_SRC="${WORKING_HOST}/icon.png"
if [ -f "${ICON_SRC}" ]; then
    cp "${ICON_SRC}" "${HOME}/.local/share/icons/hicolor/256x256/apps/ok-wuwa.png"
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true
    fi
fi

DESKTOP_PATH="${HOME}/.local/share/applications/ok-wuwa.desktop"
cat << DESKTOP_EOF > "${DESKTOP_PATH}"
[Desktop Entry]
Name=OK-WuWa
Comment=Wuthering Waves Automation Assistant (Proton/Wine)
Exec=${HOME}/.local/bin/ok-wuwa
Icon=ok-wuwa
Terminal=false
Type=Application
Categories=Game;Utility;
StartupNotify=true
DESKTOP_EOF
chmod +x "${DESKTOP_PATH}"

echo "=========================================================================="
echo " Setup Complete!"
echo ""
echo " 1. Launch anytime (before OR after starting Wuthering Waves):"
echo "    ok-wuwa   (or launch 'OK-WuWa' from your desktop menu)"
echo ""
echo " 2. Update OK-WW to the latest upstream release anytime:"
echo "    ok-wuwa --update"
echo ""
echo " 3. Optional 1-Click Steam Companion (auto-starts with Wuthering Waves):"
echo "    Steam -> Wuthering Waves -> Properties -> Launch Options:"
echo "    ~/.local/share/ok-wuwa/steam-wrapper.sh %command%"
echo "=========================================================================="
