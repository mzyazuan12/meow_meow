from __future__ import annotations

import ctypes
import time
from ctypes import c_int, c_uint16, c_uint32, c_void_p

_CG = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
_CG.CGEventCreateKeyboardEvent.restype = c_void_p
_CG.CGEventCreateKeyboardEvent.argtypes = [c_void_p, c_uint16, c_int]
_CG.CGEventPost.argtypes = [c_uint32, c_void_p]
_CG.CGEventSetFlags.argtypes = [c_void_p, c_uint32]

_HID = 0
_FLAG_SHIFT = 1 << 17

_LETTERS = {
    "a": 0x00,
    "s": 0x01,
    "d": 0x02,
    "f": 0x03,
    "h": 0x04,
    "g": 0x05,
    "z": 0x06,
    "x": 0x07,
    "c": 0x08,
    "v": 0x09,
    "b": 0x0B,
    "q": 0x0C,
    "w": 0x0D,
    "e": 0x0E,
    "r": 0x0F,
    "y": 0x10,
    "t": 0x11,
    "o": 0x1F,
    "u": 0x20,
    "i": 0x22,
    "p": 0x23,
    "l": 0x25,
    "j": 0x26,
    "k": 0x28,
    "n": 0x2D,
    "m": 0x2E,
}
_EXTRA = {
    "-": 0x1B,
    "'": 0x27,
}
_RETURN = 0x24
_DELETE = 0x33

_CF = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
_CF.CFRelease.argtypes = [c_void_p]

def _post(keycode: int, down: bool, flags: int = 0) -> None:
    event = _CG.CGEventCreateKeyboardEvent(None, c_uint16(keycode), c_int(1 if down else 0))
    if not event:
        return
    if flags:
        _CG.CGEventSetFlags(event, c_uint32(flags))
    _CG.CGEventPost(c_uint32(_HID), event)
    _CF.CFRelease(event)

def tap_key(kind: str, key: str, hold: float = 0.008) -> None:
    if kind == "back":
        _post(_DELETE, True)
        _post(_DELETE, False)
        return
    if not key:
        return
    ch = key[0]
    if ch == "\n":
        press_enter()
        return
    lower = ch.lower()
    code = _LETTERS.get(lower)
    if code is None:
        code = _EXTRA.get(ch)
    if code is None:
        return
    flags = _FLAG_SHIFT if ch.isalpha() and ch.isupper() else 0
    _post(code, True, flags)
    time.sleep(hold)
    _post(code, False, flags)

def press_enter() -> None:
    _post(_RETURN, True)
    _post(_RETURN, False)

def _objc():
    ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
    lib = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
    lib.objc_getClass.restype = c_void_p
    lib.objc_getClass.argtypes = [ctypes.c_char_p]
    lib.sel_registerName.restype = c_void_p
    lib.sel_registerName.argtypes = [ctypes.c_char_p]
    return lib

def _msg(ret, obj, sel, *args, argtypes=()):
    lib = _objc()
    send = lib.objc_msgSend
    send.restype = ret
    send.argtypes = [c_void_p, c_void_p, *argtypes]
    return send(obj, lib.sel_registerName(sel.encode()), *args)

def _nsstring(value) -> str:
    if not value:
        return ""
    raw = _msg(ctypes.c_char_p, value, "UTF8String")
    if not raw:
        return ""
    return raw.decode("utf-8", "replace")

def _ensure_app() -> None:
    _msg(c_void_p, _objc().objc_getClass(b"NSApplication"), "sharedApplication")

def _roblox_app():
    _ensure_app()
    workspace = _msg(c_void_p, _objc().objc_getClass(b"NSWorkspace"), "sharedWorkspace")
    apps = _msg(c_void_p, workspace, "runningApplications")
    count = _msg(ctypes.c_ulong, apps, "count")
    for index in range(count):
        app = _msg(c_void_p, apps, "objectAtIndex:", index, argtypes=(ctypes.c_ulong,))
        name = _nsstring(_msg(c_void_p, app, "localizedName")).lower()
        if "roblox" in name:
            return app
    return None

def _front_pid() -> int:
    _ensure_app()
    workspace = _msg(c_void_p, _objc().objc_getClass(b"NSWorkspace"), "sharedWorkspace")
    front = _msg(c_void_p, workspace, "frontmostApplication")
    if not front:
        return 0
    return int(_msg(ctypes.c_int, front, "processIdentifier"))

def roblox_running() -> bool:

    try:
        return _roblox_app() is not None
    except (OSError, AttributeError):
        return False

def focus_roblox() -> bool:

    try:
        app = _roblox_app()
    except (OSError, AttributeError):
        app = None
    if not app:
        return False
    pid = int(_msg(ctypes.c_int, app, "processIdentifier"))
    if _front_pid() == pid:
        return True

    _msg(ctypes.c_bool, app, "activateWithOptions:", 2, argtypes=(ctypes.c_ulong,))
    deadline = time.time() + 0.2
    while time.time() < deadline:
        if _front_pid() == pid:
            return True
        time.sleep(0.012)
    return _front_pid() == pid
