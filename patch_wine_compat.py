#!/usr/bin/env python3
"""
Quilt-style idempotent Wine/Proton compatibility patcher for OK-WuWa.

Design:
- Zero-pollution by default: patches ~/.local/share/ok-wuwa/app (or an explicit
  working directory / legacy Wine prefix passed on the command line).
- Pristine sources are resolved offline-first from the local git repository
  (data/apps/ok-ww/repo via git or dulwich), then ~/.cache/ok-wuwa/pristine/,
  then upstream GitHub (unless --offline is set), and finally .orig backups.
- Every apply rebuilds each module from pristine + transforms, validates its
  Python AST, and atomically replaces the target file.
- Installs a lightweight sitecustomize.py hook into the bundled Python so
  in-app self-updates automatically re-apply Wine patches on restart.
"""

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from typing import Callable, List, Optional, Tuple

DEFAULT_APP_ROOT = os.path.join(os.path.expanduser("~"), ".local", "share", "ok-wuwa", "app")
CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".cache", "ok-wuwa", "pristine")
APP_REPO = "ok-oldking/ok-ww-update"
FILE_TIMEOUT = 30

WINE_FUNC = (
    "def is_wine():\n"
    "    try:\n"
    "        import ctypes\n"
    "        return hasattr(ctypes.cdll.ntdll, 'wine_get_version')\n"
    "    except Exception:\n"
    "        return False\n\n"
)


def _http_get(url: str, timeout: int = FILE_TIMEOUT) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "ok-wuwa-patcher"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def detect_version(working_dir: str) -> Optional[str]:
    try:
        with open(os.path.join(working_dir, "config.py"), encoding="utf-8", errors="replace") as f:
            cfg = f.read()
        m = re.search(r'^version\s*=\s*"(v[\d.]+[^"]*)"', cfg, re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    app_json = os.path.normpath(os.path.join(working_dir, "..", "app.json"))
    if os.path.isfile(app_json):
        try:
            with open(app_json, encoding="utf-8") as f:
                return json.load(f).get("current_version")
        except Exception:
            pass
    return None


class PristineSource:
    """Resolves pristine unpatched file contents:
    1. Local git repo (../repo or working/.git) via git CLI or dulwich
    2. Local disk cache (~/.cache/ok-wuwa/pristine/<version>/)
    3. Upstream raw.githubusercontent.com (skipped when offline=True)
    4. Local .orig snapshot next to target file
    """

    def __init__(self, working_dir: str, version: Optional[str], offline: bool = False):
        self.working_dir = working_dir
        self.version = version
        self.offline = offline
        self.cache_dir = os.path.join(CACHE_ROOT, version or "unknown")
        self.net_ok = not offline
        self.git_dir = self._find_git_dir(working_dir)

    @staticmethod
    def _find_git_dir(working_dir: str) -> Optional[str]:
        bare_repo = os.path.normpath(os.path.join(working_dir, "..", "repo"))
        if os.path.isdir(os.path.join(bare_repo, "objects")):
            return bare_repo
        dot_git = os.path.join(working_dir, ".git")
        if os.path.isdir(dot_git):
            return dot_git
        if os.path.isdir(os.path.join(bare_repo, ".git")):
            return os.path.join(bare_repo, ".git")
        return None

    def _from_local_git(self, rel: str) -> Optional[str]:
        if not self.git_dir:
            return None
        ref = self.version or "HEAD"
        if shutil.which("git"):
            for candidate_ref in (ref, "HEAD"):
                try:
                    res = subprocess.run(
                        ["git", f"--git-dir={self.git_dir}", "show", f"{candidate_ref}:{rel}"],
                        capture_output=True,
                        check=False,
                        timeout=5,
                    )
                    if res.returncode == 0 and res.stdout:
                        return res.stdout.decode("utf-8", "replace")
                except Exception:
                    pass
        try:
            from dulwich.object_store import tree_lookup_path
            from dulwich.repo import Repo

            repo = Repo(self.git_dir)
            try:
                commit_id = None
                if self.version:
                    tag_ref = f"refs/tags/{self.version}".encode("utf-8")
                    if tag_ref in repo.refs:
                        commit_id = repo.refs[tag_ref]
                if commit_id is None:
                    commit_id = repo.head()
                obj = repo[commit_id]
                while getattr(obj, "type_name", None) == b"tag":
                    obj = repo[obj.object[1]]
                _, blob_sha = tree_lookup_path(repo.object_store.__getitem__, obj.tree, rel.encode("utf-8"))
                return repo.object_store[blob_sha].data.decode("utf-8", "replace")
            finally:
                repo.close()
        except Exception:
            return None

    def _cache_path(self, rel: str) -> str:
        return os.path.join(self.cache_dir, rel.replace("/", os.sep) + ".pristine")

    def _load_cache(self, rel: str) -> Optional[str]:
        p = self._cache_path(rel)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace", newline="") as f:
                return f.read()
        return None

    def _store_cache(self, rel: str, content: str) -> None:
        try:
            p = self._cache_path(rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        except OSError:
            pass

    def _fetch_upstream(self, rel: str) -> Optional[str]:
        if not self.version or not self.net_ok:
            return None
        try:
            raw = _http_get(f"https://raw.githubusercontent.com/{APP_REPO}/{self.version}/{rel}")
            return raw.decode("utf-8", "replace") if raw is not None else None
        except Exception:
            self.net_ok = False
            print(f"  [WARN] Upstream fetch failed for {rel}; using local .orig backup.")
            return None

    def get(self, file_path: str, rel: str) -> Optional[str]:
        git_content = self._from_local_git(rel)
        if git_content is not None:
            return git_content
        cached = self._load_cache(rel)
        if cached is not None:
            return cached
        fetched = self._fetch_upstream(rel)
        if fetched is not None:
            self._store_cache(rel, fetched)
            return fetched
        orig = file_path + ".orig"
        if os.path.isfile(orig):
            with open(orig, encoding="utf-8", errors="replace", newline="") as f:
                return f.read()
        # First-time offline fallback when the target file itself is still pristine
        if os.path.isfile(file_path):
            with open(file_path, encoding="utf-8", errors="replace", newline="") as f:
                cur = f.read()
            if "def is_wine():" not in cur and "fallback=True" not in cur and "clean_up_bitblt(context)" not in cur.splitlines()[55:65]:
                return cur
        return None


# ------------------------- patch transforms -------------------------

def _sub(content: str, old: str, new: str, label: str) -> Tuple[str, List[str]]:
    if old not in content:
        return content, [label]
    return content.replace(old, new), []


def _t_kit_theme(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    old = (
        "def backdrop_supported(backdrop) -> bool:\n"
        '    """Whether DWM on this system can draw ``backdrop``."""\n'
        "\n"
        "    backdrop = Backdrop(backdrop)\n"
        "    if backdrop == Backdrop.NONE:\n"
        "        return True"
    )
    new = (
        "def backdrop_supported(backdrop) -> bool:\n"
        '    """Whether DWM on this system can draw ``backdrop``."""\n'
        "\n"
        "    backdrop = Backdrop(backdrop)\n"
        "    if backdrop == Backdrop.NONE:\n"
        "        return True\n"
        "    if is_wine():\n"
        "        return False"
    )
    return _sub(content, old, new, "kit theme backdrop guard")


def _t_run_bar(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    old_init = (
        "        self.basic_options = og.executor.basic_options\n"
        "        self.current_hotkey = \"UNINIT\"\n"
        "        self.handler = Handler(exit_event, \"RunBarHotkey\")\n"
        "        self.handler.post(self._check_hotkey, 0.1)\n"
        "        self.refresh()"
    )
    new_init = (
        "        self.basic_options = og.executor.basic_options\n"
        "        self.current_hotkey = \"UNINIT\"\n"
        "        self._wine_hotkey_down = False\n"
        "        self._wine_hotkey_timer = None\n"
        "        if is_wine():\n"
        "            self.handler = None\n"
        "            self._wine_hotkey_timer = QTimer(self)\n"
        "            self._wine_hotkey_timer.setInterval(80)\n"
        "            self._wine_hotkey_timer.timeout.connect(self._poll_wine_hotkey)\n"
        "            self._wine_hotkey_timer.start()\n"
        "        else:\n"
        "            self.handler = Handler(exit_event, \"RunBarHotkey\")\n"
        "            self.handler.post(self._check_hotkey, 0.1)\n"
        "        self.refresh()"
    )
    content, m1 = _sub(content, old_init, new_init, "RunBar GUI-thread hotkey timer")

    old_dispose = (
        "    def dispose(self) -> None:\n"
        '        """Release the hotkey and stop polling so a replacement run bar can bind it."""\n'
        "        self.timer.stop()\n"
        "        self.handler.post(self._release_hotkey)\n"
        "        self.handler.join(1)"
    )
    new_dispose = (
        "    def dispose(self) -> None:\n"
        '        """Release the hotkey and stop polling so a replacement run bar can bind it."""\n'
        "        self.timer.stop()\n"
        "        if self._wine_hotkey_timer is not None:\n"
        "            self._wine_hotkey_timer.stop()\n"
        "            return\n"
        "        if self.handler is not None:\n"
        "            self.handler.post(self._release_hotkey)\n"
        "            self.handler.join(1)\n\n"
        "    def _poll_wine_hotkey(self) -> None:\n"
        "        hk = self.basic_options.get('Start/Stop')\n"
        "        vk = HOTKEY_KEYS.get(hk) if hk and hk != 'None' else None\n"
        "        if not vk:\n"
        "            self._wine_hotkey_down = False\n"
        "            return\n"
        "        down = bool(windll.user32.GetAsyncKeyState(vk) & 0x8000)\n"
        "        if down and not self._wine_hotkey_down:\n"
        "            self.toggle_requested.emit()\n"
        "        self._wine_hotkey_down = down"
    )
    content, m2 = _sub(content, old_dispose, new_dispose, "RunBar dispose & GetAsyncKeyState poller")
    return content, m1 + m2


def _t_diagnosis_page(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    old_init = (
        "        self.hotkey_handler = None\n"
        "        if debug and exit_event is not None:\n"
        "            from ok import Handler\n"
        "            # Hotkeys are registered to, and polled on, their own thread so that a\n"
        "            # busy tool (capture waiting for WGC) cannot block Ctrl+Alt+D.\n"
        "            self.hotkey_handler = Handler(exit_event, \"DiagnosisHotkeys\")\n"
        "            self.hotkey_handler.post(self.bind_hot_keys)\n"
        "            self.hotkey_handler.post(self.check_hotkey, 0.1)\n"
        "            og.app.app.aboutToQuit.connect(self.unregister)"
    )
    new_init = (
        "        self.hotkey_handler = None\n"
        "        self._wine_diag_down = (False, False)\n"
        "        if debug and exit_event is not None:\n"
        "            if is_wine():\n"
        "                self._wine_diag_timer = QTimer(self)\n"
        "                self._wine_diag_timer.setInterval(100)\n"
        "                self._wine_diag_timer.timeout.connect(self._poll_wine_diag_hotkeys)\n"
        "                self._wine_diag_timer.start()\n"
        "            else:\n"
        "                from ok import Handler\n"
        "                self.hotkey_handler = Handler(exit_event, \"DiagnosisHotkeys\")\n"
        "                self.hotkey_handler.post(self.bind_hot_keys)\n"
        "                self.hotkey_handler.post(self.check_hotkey, 0.1)\n"
        "                og.app.app.aboutToQuit.connect(self.unregister)"
    )
    content, m1 = _sub(content, old_init, new_init, "DiagnosisPage Wine hotkey timer")

    old_unreg = (
        "    @staticmethod\n"
        "    def unregister() -> None:\n"
        "        windll.user32.UnregisterHotKey(None, HOTKEY_DUMP)\n"
        "        windll.user32.UnregisterHotKey(None, HOTKEY_CAPTURE)"
    )
    new_unreg = (
        "    def _poll_wine_diag_hotkeys(self) -> None:\n"
        "        ctrl = bool(windll.user32.GetAsyncKeyState(0x11) & 0x8000)\n"
        "        alt = bool(windll.user32.GetAsyncKeyState(0x12) & 0x8000)\n"
        "        d_down = ctrl and alt and bool(windll.user32.GetAsyncKeyState(0x44) & 0x8000)\n"
        "        s_down = ctrl and alt and bool(windll.user32.GetAsyncKeyState(0x53) & 0x8000)\n"
        "        prev_d, prev_s = self._wine_diag_down\n"
        "        if d_down and not prev_d:\n"
        "            from ok.capture.windows.dump import dump_threads\n"
        "            dump_threads()\n"
        "        if s_down and not prev_s:\n"
        "            diagnostics.capture_screenshot(done=self.capture_done.emit)\n"
        "        self._wine_diag_down = (d_down, s_down)\n\n"
        "    @staticmethod\n"
        "    def unregister() -> None:\n"
        "        if is_wine():\n"
        "            return\n"
        "        windll.user32.UnregisterHotKey(None, HOTKEY_DUMP)\n"
        "        windll.user32.UnregisterHotKey(None, HOTKEY_CAPTURE)"
    )
    content, m2 = _sub(content, old_unreg, new_unreg, "DiagnosisPage GetAsyncKeyState poller")
    return content, m1 + m2


def _t_window(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    content, m1 = _sub(
        content,
        "def windows_graphics_available():\n",
        "def windows_graphics_available():\n    if is_wine():\n        return False\n",
        "windows_graphics_available guard",
    )
    old_fg = (
        "def is_foreground_window(hwnd):\n"
        "    return win32gui.IsWindowVisible(hwnd) and win32gui.GetForegroundWindow() == hwnd"
    )
    new_fg = (
        "def is_foreground_window(hwnd):\n"
        "    if is_wine() and os.environ.get('OKWW_REQUIRE_FOREGROUND') != '1':\n"
        "        return bool(win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd))\n"
        "    return win32gui.IsWindowVisible(hwnd) and win32gui.GetForegroundWindow() == hwnd"
    )
    content, m2 = _sub(content, old_fg, new_fg, "is_foreground_window background mode")
    return content, m1 + m2


def _t_post_message(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    old_send_key = (
        "    def send_key(self, key, down_time=0.01):\n"
        "        super().send_key(key, down_time)\n"
        "        self.send_key_down(key)\n"
        "        time.sleep(down_time)\n"
        "        self.send_key_up(key)"
    )
    new_send_key = (
        "    def send_key(self, key, down_time=0.01):\n"
        "        if is_wine() and down_time < 0.04:\n"
        "            down_time = 0.04\n"
        "        super().send_key(key, down_time)\n"
        "        self.send_key_down(key)\n"
        "        time.sleep(down_time)\n"
        "        self.send_key_up(key)"
    )
    content, m1 = _sub(content, old_send_key, new_send_key, "send_key 0.04s minimum down_time")

    old_activate = (
        "    def try_activate(self):\n"
        "        base_hwnd = self.hwnd_window.hwnd\n"
        "        current_hwnd = self.hwnd\n"
        "\n"
        "        self.activate(base_hwnd)\n"
        "        if current_hwnd != base_hwnd:\n"
        "            self.activate(current_hwnd)"
    )
    new_activate = (
        "    def try_activate(self):\n"
        "        if is_wine():\n"
        "            return\n"
        "        base_hwnd = self.hwnd_window.hwnd\n"
        "        current_hwnd = self.hwnd\n"
        "\n"
        "        self.activate(base_hwnd)\n"
        "        if current_hwnd != base_hwnd:\n"
        "            self.activate(current_hwnd)"
    )
    content, m2 = _sub(content, old_activate, new_activate, "try_activate focus-steal prevention")

    old_click = (
        "    def click(self, x=-1, y=-1, move_back=False, name=None, down_time=0.01, move=True, key=\"left\"):\n"
        "        super().click(x, y, name=name)"
    )
    new_click = (
        "    def click(self, x=-1, y=-1, move_back=False, name=None, down_time=0.01, move=True, key=\"left\"):\n"
        "        if is_wine() and down_time < 0.04:\n"
        "            down_time = 0.04\n"
        "        super().click(x, y, name=name)"
    )
    content, m3 = _sub(content, old_click, new_click, "click 0.04s minimum down_time")

    old_rclick = (
        "    def right_click(self, x=-1, y=-1, move_back=False, name=None):\n"
        "        super().right_click(x, y, name=name)\n"
        "        long_position = self.update_mouse_pos(x, y)\n"
        "        self.post(win32con.WM_RBUTTONDOWN, win32con.MK_RBUTTON, long_position)\n"
        "        self.post(win32con.WM_RBUTTONUP, 0, long_position)"
    )
    new_rclick = (
        "    def right_click(self, x=-1, y=-1, move_back=False, name=None):\n"
        "        self.click(x, y, move_back=move_back, name=name, key=\"right\")"
    )
    content, m4 = _sub(content, old_rclick, new_rclick, "right_click delegate fix")
    return content, m1 + m2 + m3 + m4


def _t_bitblt(content: str) -> Tuple[str, List[str]]:
    return _sub(
        content,
        "def capture_by_bitblt(context, hwnd, width, height, x, y, render_full_content):\n"
        "    if hwnd <= 0 or width <= 0 or height <= 0:\n"
        "        logger.error(f'capture_by_bitblt invalid params: hwnd={hwnd}, w={width}, h={height}')\n"
        "        return None",
        "def capture_by_bitblt(context, hwnd, width, height, x, y, render_full_content):\n"
        "    if hwnd <= 0 or width <= 0 or height <= 0:\n"
        "        return None\n"
        "    if not win32gui.IsWindow(hwnd):\n"
        "        clean_up_bitblt(context)\n"
        "        return None",
        "BitBlt invalid HWND guard",
    )


def _t_translation(content: str) -> Tuple[str, List[str]]:
    content, m1 = _sub(
        content,
        "return gettext.translation('ok', dir_i18n, languages=fallback_list)",
        "return gettext.translation('ok', dir_i18n, languages=fallback_list, fallback=True)",
        "ok translation fallback",
    )
    content, m2 = _sub(
        content,
        "return gettext.translation('ocr', dir_i18n, languages=fallback_list)",
        "return gettext.translation('ocr', dir_i18n, languages=fallback_list, fallback=True)",
        "ocr translation fallback",
    )
    return content, m1 + m2


def _t_explorer(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    return _sub(
        content,
        "    if _focus_existing_explorer_window(folder, item_name):\n"
        "        logger.info(f'Explorer focused existing window: folder={str(folder)!r}')\n"
        "        return True",
        "    if is_wine():\n"
        "        os.startfile(str(folder), 'explore')\n"
        "        logger.info('Explorer launch request completed (Wine)')\n"
        "        return True\n"
        "    if _focus_existing_explorer_window(folder, item_name):\n"
        "        logger.info(f'Explorer focused existing window: folder={str(folder)!r}')\n"
        "        return True",
        "Explorer Wine COM bypass",
    )


def _t_process(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    content, m1 = _sub(
        content,
        "def get_first_gpu_free_memory_mib():\n",
        "def get_first_gpu_free_memory_mib():\n    if is_wine():\n        return -1\n",
        "nvidia-smi guard",
    )
    old_exec = (
        "def execute(game_cmd: str, arguments=None, start_method=WINDOWS_START_METHOD_START):\n"
        "    if game_cmd:\n"
        "        if '://' in game_cmd:\n"
        "            try:\n"
        "                logger.info(f'try execute url {game_cmd}')\n"
        "                os.startfile(game_cmd)\n"
        "                return True"
    )
    new_exec = (
        "def execute(game_cmd: str, arguments=None, start_method=WINDOWS_START_METHOD_START):\n"
        "    if game_cmd:\n"
        "        if '://' in game_cmd:\n"
        "            handoff = os.environ.get('OKWW_HANDOFF_FILE')\n"
        "            if is_wine() and handoff and game_cmd.startswith('steam://'):\n"
        "                try:\n"
        "                    task_name = ''\n"
        "                    try:\n"
        "                        from ok import og\n"
        "                        sc = getattr(getattr(og, 'app', None), 'start_controller', None)\n"
        "                        active = getattr(sc, '_active_task', None) if sc else None\n"
        "                        if active is not None and hasattr(active, 'name'):\n"
        "                            task_name = str(active.name)\n"
        "                    except Exception:\n"
        "                        pass\n"
        "                    with open(handoff, 'w', encoding='utf-8') as hf:\n"
        "                        json.dump({'url': game_cmd, 'task': task_name}, hf)\n"
        "                    logger.info(f'Wrote Steam container handoff to {handoff}')\n"
        "                    os._exit(75)\n"
        "                except Exception as e:\n"
        "                    logger.error('handoff write error', e)\n"
        "            try:\n"
        "                logger.info(f'try execute url {game_cmd}')\n"
        "                os.startfile(game_cmd)\n"
        "                return True"
    )
    content, m2 = _sub(content, old_exec, new_exec, "Steam container handoff hook")
    return content, m1 + m2


def _t_config(content: str) -> Tuple[str, List[str]]:
    content = WINE_FUNC + content
    old_calc = (
        "def calculate_pc_exe_path(running_path):\n"
        "    if running_path is None:\n"
        "        return _find_most_recently_run_pc_exe() or _find_pc_exe_from_registry()\n"
        "    game_exe_folder = Path(running_path).parents[3]\n"
        "    return str(game_exe_folder / \"Wuthering Waves.exe\")"
    )
    new_calc = (
        "def calculate_pc_exe_path(running_path):\n"
        "    if running_path is None:\n"
        "        if is_wine():\n"
        "            return 'steam://rungameid/3513350'\n"
        "        return _find_most_recently_run_pc_exe() or _find_pc_exe_from_registry()\n"
        "    game_exe_folder = Path(running_path).parents[3]\n"
        "    return str(game_exe_folder / \"Wuthering Waves.exe\")"
    )
    return _sub(content, old_calc, new_calc, "Steam URI launcher path")


def _t_ok_init(content: str) -> Tuple[str, List[str]]:
    return _sub(
        content,
        "        elif self.global_config.get_config(basic_options).get('Auto Start Game When App Starts'):\n"
        "            logger.info('start runtime with Auto Start Game When App Starts')\n"
        "            app.start_controller.start()",
        "        elif self.global_config.get_config(basic_options).get('Auto Start Game When App Starts') or os.environ.get('OKWW_AUTO_START') == '1':\n"
        "            logger.info('start runtime with Auto Start Game When App Starts')\n"
        "            app.start_controller.start()",
        "OKWW_AUTO_START handoff resume",
    )


# (relpath, transform, marker, description)
PATCH_SPECS: List[Tuple[str, Callable[[str], Tuple[str, List[str]]], str, str]] = [
    ("ok/ui/qt/kit/theme.py", _t_kit_theme, "is_wine", "Kit Window Solid Backdrop (Disable DWM Mica/Acrylic)"),
    ("ok/ui/qt/shell/run_bar.py", _t_run_bar, "_poll_wine_hotkey", "RunBar F9-F12 Hotkey (GUI-Thread GetAsyncKeyState)"),
    ("ok/ui/qt/debug/diagnosis_page.py", _t_diagnosis_page, "_poll_wine_diag_hotkeys", "Diagnosis Hotkeys (Deadlock-Free GetAsyncKeyState)"),
    ("ok/util/window.py", _t_window, "OKWW_REQUIRE_FOREGROUND", "Window WGC Bypass & Background Focus Support"),
    ("ok/device/interaction_methods/post_message.py", _t_post_message, "down_time < 0.04", "PostMessage Focus-Steal Guard & 40ms Frame Hold"),
    ("ok/device/capture_methods/bitblt_utils.py", _t_bitblt, "if not win32gui.IsWindow(hwnd):\n        clean_up_bitblt(context)", "BitBlt Stale HWND Guard"),
    ("ok/core/translation.py", _t_translation, "fallback=True", "Gettext Locale Fallback"),
    ("ok/util/explorer.py", _t_explorer, "is_wine", "Explorer Launch COM Bypass"),
    ("ok/util/process.py", _t_process, "OKWW_HANDOFF_FILE", "GPU Probe Guard & Steam Container Handoff"),
    ("config.py", _t_config, "steam://rungameid/3513350", "Anti-Cheat Safe Steam Game Launch"),
    ("ok/__init__.py", _t_ok_init, "OKWW_AUTO_START", "Handoff Auto-Start Resume"),
]

SITECUSTOMIZE_CODE = '''"""Auto-reapply OK-WuWa Wine compatibility patches after in-app updates."""
import os
import sys

def _okww_auto_patch():
    try:
        import ctypes
        if not hasattr(ctypes.cdll.ntdll, "wine_get_version"):
            return
    except Exception:
        return
    if not sys.argv or not any(os.path.basename(a).startswith("main") and a.endswith(".py") for a in sys.argv[:2]):
        return
    py_dir = os.path.dirname(os.path.abspath(sys.executable))
    app_dir = os.path.normpath(os.path.join(py_dir, ".."))
    working = os.path.join(app_dir, "working")
    cfg = os.path.join(working, "config.py")
    if not os.path.isfile(cfg):
        return
    try:
        with open(cfg, encoding="utf-8", errors="replace") as f:
            if "def is_wine():" in f.read(512):
                return
    except OSError:
        return
    patcher_candidates = [
        os.path.normpath(os.path.join(app_dir, "..", "..", "..", "..", "patch_wine_compat.py")),
        os.path.join(os.path.dirname(working), "patch_wine_compat.py"),
    ]
    for cand in patcher_candidates:
        if os.path.isfile(cand):
            import importlib.util
            spec = importlib.util.spec_from_file_location("_okww_patcher", cand)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.PatchEngine([working], offline=True).apply_patches()
            break

_okww_auto_patch()
'''


# ------------------------- engine -------------------------

def discover_working_dirs(target: str) -> List[str]:
    """Locate deduplicated OK-WW working directories under an app root, working dir, or Wine prefix."""
    target = os.path.abspath(os.path.expanduser(target))
    candidates = []

    if os.path.isfile(os.path.join(target, "main.py")) and os.path.isfile(os.path.join(target, "config.py")):
        candidates.append(target)

    direct_wk = os.path.join(target, "data", "apps", "ok-ww", "working")
    if os.path.isfile(os.path.join(direct_wk, "main.py")):
        candidates.append(direct_wk)

    pfx = target
    if os.path.isdir(os.path.join(target, "pfx")):
        pfx = os.path.join(target, "pfx")
    users_dir = os.path.join(pfx, "drive_c", "users")
    if os.path.isdir(users_dir):
        for entry in sorted(os.listdir(users_dir)):
            wk = os.path.join(users_dir, entry, "AppData", "Local", "ok-ww", "data", "apps", "ok-ww", "working")
            if os.path.isfile(os.path.join(wk, "main.py")):
                candidates.append(wk)

    seen_real = set()
    unique = []
    for wk in candidates:
        real = os.path.realpath(wk)
        if real not in seen_real:
            seen_real.add(real)
            unique.append(real)
    return unique


class PatchEngine:
    def __init__(self, working_dirs: List[str], offline: bool = False):
        self.working_dirs = working_dirs
        self.offline = offline

    @staticmethod
    def _safe_write(file_path: str, content: str) -> bool:
        if file_path.endswith(".py"):
            try:
                ast.parse(content, filename=file_path)
            except SyntaxError as e:
                print(f"  [ERROR] AST validation failed for {file_path}: {e}")
                return False
        d = os.path.dirname(file_path)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".okww-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(content.encode("utf-8"))
            os.replace(tmp, file_path)
            return True
        except Exception as e:
            print(f"  [ERROR] Write failed for {file_path}: {e}")
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return False

    @staticmethod
    def _with_native_eol(transform: Callable[[str], Tuple[str, List[str]]], content: str) -> Tuple[str, List[str]]:
        eol = "\r\n" if "\r\n" in content else "\n"
        normalized = content.replace("\r\n", "\n")
        patched, missing = transform(normalized)
        if eol == "\r\n":
            patched = patched.replace("\n", "\r\n").replace("\r\r\n", "\r\n")
        return patched, missing

    @staticmethod
    def _install_sitecustomize(working_dir: str) -> None:
        sp = os.path.normpath(os.path.join(working_dir, "..", "python", "Lib", "site-packages"))
        if os.path.isdir(sp):
            sc = os.path.join(sp, "sitecustomize.py")
            PatchEngine._safe_write(sc, SITECUSTOMIZE_CODE)

    @staticmethod
    def _remove_sitecustomize(working_dir: str) -> None:
        sc = os.path.normpath(os.path.join(working_dir, "..", "python", "Lib", "site-packages", "sitecustomize.py"))
        if os.path.isfile(sc):
            try:
                with open(sc, encoding="utf-8", errors="replace") as f:
                    if "_okww_auto_patch" in f.read(256):
                        os.unlink(sc)
            except OSError:
                pass

    def apply_patches(self) -> bool:
        if not self.working_dirs:
            print("[WARN] No OK-WW installation found to patch.")
            return True
        ok = True
        for working_dir in self.working_dirs:
            version = detect_version(working_dir)
            print(f"[*] Patching OK-WW ({version or 'unknown'}) in {working_dir}...")
            source = PristineSource(working_dir, version, offline=self.offline)
            for rel, transform, _, _ in PATCH_SPECS:
                fp = os.path.join(working_dir, rel)
                if not os.path.isfile(fp):
                    continue
                pristine = source.get(fp, rel)
                if pristine is None:
                    print(f"  [WARN] No pristine source for {rel}; skipping.")
                    continue
                orig = fp + ".orig"
                if not os.path.isfile(orig):
                    with open(orig, "w", encoding="utf-8", newline="") as f:
                        f.write(pristine)
                patched, missing = self._with_native_eol(transform, pristine)
                for m in missing:
                    print(f"  [WARN] Patch site missing in {rel}: {m}")
                if not self._safe_write(fp, patched):
                    ok = False
                else:
                    print(f"  -> Patched {rel}")
            self._install_sitecustomize(working_dir)
        return self.verify() and ok

    def revert_patches(self) -> bool:
        restored = 0
        for working_dir in self.working_dirs:
            version = detect_version(working_dir)
            source = PristineSource(working_dir, version, offline=self.offline)
            for rel, _, _, _ in PATCH_SPECS:
                fp = os.path.join(working_dir, rel)
                if not os.path.isfile(fp):
                    continue
                pristine = source.get(fp, rel)
                if pristine is not None and self._safe_write(fp, pristine):
                    restored += 1
                    try:
                        os.unlink(fp + ".orig")
                    except OSError:
                        pass
            self._remove_sitecustomize(working_dir)
        print(f"[*] Restored {restored} file(s) to pristine upstream state.")
        return True

    def verify(self) -> bool:
        errors = 0
        checked = 0
        for working_dir in self.working_dirs:
            for rel, _, _, _ in PATCH_SPECS:
                fp = os.path.join(working_dir, rel)
                if os.path.isfile(fp):
                    checked += 1
                    try:
                        with open(fp, encoding="utf-8") as f:
                            ast.parse(f.read(), filename=fp)
                    except SyntaxError as e:
                        print(f"  [FAIL] {rel}: {e}")
                        errors += 1
        if checked == 0:
            print("  [WARN] 0 modules checked (OK-WW not installed yet).")
            return True
        if errors == 0:
            print(f"  -> All {checked} patched modules passed AST validation.")
        return errors == 0

    def get_status(self) -> None:
        if not self.working_dirs:
            print("  -> No OK-WW working directory found.")
            return
        for working_dir in self.working_dirs:
            version = detect_version(working_dir)
            print(f"[*] Target: {working_dir} (version: {version or 'unknown'})")
            for rel, _, marker, desc in PATCH_SPECS:
                fp = os.path.join(working_dir, rel)
                if not os.path.isfile(fp):
                    print(f"  [ ] {desc} (missing: {rel})")
                    continue
                with open(fp, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                applied = marker in content
                has_orig = os.path.isfile(fp + ".orig")
                print(f"  [{'x' if applied else ' '}] {desc} [backup: {has_orig}]")


def ensure_local_icu_dlls(working_dirs: List[str], prefix_path: Optional[str] = None) -> None:
    """Zero-pollution ICU fallback: if an older Wine prefix lacks icuuc.dll or
    icuin.dll in system32, place copies next to bundled python.exe instead of
    modifying the game's Proton prefix."""
    if not prefix_path:
        return
    pfx = os.path.join(prefix_path, "pfx") if os.path.isdir(os.path.join(prefix_path, "pfx")) else prefix_path
    sys32 = os.path.join(pfx, "drive_c", "windows", "system32")
    icu_src = os.path.join(sys32, "icu.dll")
    if not os.path.isfile(icu_src):
        return
    need_aliases = [
        alias for alias in ("icuuc.dll", "icuin.dll")
        if not os.path.isfile(os.path.join(sys32, alias))
    ]
    if not need_aliases:
        return
    for wk in working_dirs:
        py_dir = os.path.normpath(os.path.join(wk, "..", "python"))
        if os.path.isdir(py_dir):
            for alias in need_aliases:
                dst = os.path.join(py_dir, alias)
                if not os.path.isfile(dst):
                    shutil.copy2(icu_src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description="Quilt-style idempotent Wine/Proton patcher for OK-WuWa")
    parser.add_argument(
        "target",
        nargs="?",
        default=DEFAULT_APP_ROOT,
        help="Path to OK-WuWa app root (~/.local/share/ok-wuwa/app), working dir, or Wine prefix",
    )
    parser.add_argument("--prefix", help="Optional Wine prefix path for zero-pollution ICU DLL check")
    parser.add_argument("--revert", "--undo", action="store_true", help="Restore all patched files to pristine upstream")
    parser.add_argument("--status", action="store_true", help="Display patch application status")
    parser.add_argument("--verify", action="store_true", help="Validate Python AST syntax of all target files")
    parser.add_argument("--offline", action="store_true", help="Disable network fallback; use local git/cache/.orig only")

    args = parser.parse_args()
    working_dirs = discover_working_dirs(args.target)
    if not working_dirs and args.target != DEFAULT_APP_ROOT:
        print(f"Error: Could not find OK-WW installation under '{args.target}'", file=sys.stderr)
        sys.exit(1)

    ensure_local_icu_dlls(working_dirs, args.prefix)
    engine = PatchEngine(working_dirs, offline=args.offline)

    if args.revert:
        engine.revert_patches()
    elif args.status:
        engine.get_status()
    elif args.verify:
        if not engine.verify():
            sys.exit(1)
    else:
        if not engine.apply_patches():
            sys.exit(1)


if __name__ == "__main__":
    main()
