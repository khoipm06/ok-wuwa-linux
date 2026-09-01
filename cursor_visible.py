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
x11.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                           ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                           ctypes.POINTER(ctypes.c_uint)]
x11.XQueryTree.restype = ctypes.c_int
x11.XFree.argtypes = [ctypes.c_void_p]
x11.XFree.restype = ctypes.c_int
x11.XFetchName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_char_p)]
x11.XFetchName.restype = ctypes.c_int
xcursor.XcursorLibraryLoadCursor.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
xcursor.XcursorLibraryLoadCursor.restype = ctypes.c_ulong

TIMEOUT = 180
GONE_EXIT = 30


def find_okww_window(dpy):
    # No xprop: the Steam flatpak sandbox ships no xprop binary.
    root = x11.XDefaultRootWindow(dpy)
    rroot = ctypes.c_ulong()
    rparent = ctypes.c_ulong()
    children = ctypes.POINTER(ctypes.c_ulong)()
    nchildren = ctypes.c_uint()
    if not x11.XQueryTree(dpy, root, ctypes.byref(rroot), ctypes.byref(rparent),
                          ctypes.byref(children), ctypes.byref(nchildren)):
        return 0
    try:
        for i in range(nchildren.value):
            win = children[i]
            name = ctypes.c_char_p()
            if x11.XFetchName(dpy, win, ctypes.byref(name)):
                try:
                    if name.value and b"ok-ww" in name.value:
                        return win
                finally:
                    x11.XFree(name)
    finally:
        x11.XFree(children)
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
        win = find_okww_window(dpy)
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
