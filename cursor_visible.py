#!/usr/bin/env python3
"""
cursor_visible.py - Make the mouse cursor visible over the ok-ww window on KWin/XWayland.

KWin renders no cursor over XWayland windows whose X cursor is None (the
ok-ww Tauri window never defines one, unlike GTK apps). Defining the theme's
left_ptr cursor on the window makes KWin display it. The define survives
moves/resizes and only needs re-applying if wine recreates the window, so
this watcher re-defines whenever the window id changes.
"""
import ctypes
import ctypes.util
import subprocess
import sys
import time

x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
xcursor = ctypes.CDLL(ctypes.util.find_library("Xcursor"))

x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x11.XDefaultRootWindow.restype = ctypes.c_ulong
x11.XFlush.argtypes = [ctypes.c_void_p]
x11.XFlush.restype = ctypes.c_int
x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
x11.XSync.restype = ctypes.c_int
x11.XDefineCursor.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
x11.XDefineCursor.restype = ctypes.c_int
xcursor.XcursorLibraryLoadCursor.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
xcursor.XcursorLibraryLoadCursor.restype = ctypes.c_ulong

TIMEOUT = 180
GONE_EXIT = 30


def find_okww_window():
    out = subprocess.run(["xprop", "-display", ":0", "-root", "_NET_CLIENT_LIST"],
                         capture_output=True, text=True).stdout
    for w in out.replace("_NET_CLIENT_LIST(WINDOW):", "").replace("window id #", "").split():
        w = w.strip().strip(",")
        if not w.startswith("0x"):
            continue
        n = subprocess.run(["xprop", "-display", ":0", "-id", w, "WM_NAME"],
                           capture_output=True, text=True).stdout
        if '"ok-ww"' in n:
            return int(w, 16)
    return 0


def main():
    dpy = x11.XOpenDisplay(None)
    if not dpy:
        sys.exit(2)
    cursor = xcursor.XcursorLibraryLoadCursor(dpy, b"left_ptr")
    if not cursor:
        sys.exit(3)

    deadline = time.time() + TIMEOUT
    last_win = 0
    gone_since = 0
    while True:
        win = find_okww_window()
        if win:
            gone_since = 0
            if win != last_win:
                x11.XDefineCursor(dpy, win, cursor)
                x11.XSync(dpy, 0)
                last_win = win
        elif last_win:
            if gone_since == 0:
                gone_since = time.time()
            elif time.time() - gone_since > GONE_EXIT:
                break
        if not win and time.time() > deadline:
            break
        time.sleep(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
