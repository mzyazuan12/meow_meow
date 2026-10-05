from __future__ import annotations

import ctypes
import time
from contextlib import contextmanager
from functools import lru_cache
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
    if hasattr(_CG, "CGPreflightPostEventAccess"):
        _CG.CGPreflightPostEventAccess.restype = ctypes.c_bool
        if not _CG.CGPreflightPostEventAccess():
            raise PermissionError("Allow Accessibility for Python or Terminal in macOS Settings")
    event = _CG.CGEventCreateKeyboardEvent(None, c_uint16(keycode), c_int(1 if down else 0))
    if not event:
        raise OSError("macOS couldn't create a keyboard event")
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

@lru_cache(maxsize=1)
def _objc():
    ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
    lib = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
    lib.objc_getClass.restype = c_void_p
    lib.objc_getClass.argtypes = [ctypes.c_char_p]
    lib.sel_registerName.restype = c_void_p
    lib.sel_registerName.argtypes = [ctypes.c_char_p]
    return lib

@lru_cache(maxsize=16)
def _sender(ret, argtypes):
    # Independent signatures prevent concurrent status/input calls from changing
    # objc_msgSend's shared ctypes prototype.
    return ctypes.CFUNCTYPE(ret, c_void_p, c_void_p, *argtypes)(("objc_msgSend", _objc()))


def _msg(ret, obj, sel, *args, argtypes=()):
    lib = _objc()
    return _sender(ret, tuple(argtypes))(obj, lib.sel_registerName(sel.encode()), *args)


@contextmanager
def _autorelease_pool():
    pool = _msg(c_void_p, _objc().objc_getClass(b"NSAutoreleasePool"), "alloc")
    pool = _msg(c_void_p, pool, "init")
    try:
        yield
    finally:
        _msg(None, pool, "drain")

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
        if name in ("roblox", "robloxplayer", "robloxplayerbeta"):
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
        with _autorelease_pool():
            return _roblox_app() is not None
    except (OSError, AttributeError):
        return False


def roblox_focused() -> bool:
    try:
        with _autorelease_pool():
            app = _roblox_app()
            return bool(app and _front_pid() == int(_msg(ctypes.c_int, app, "processIdentifier")))
    except (OSError, AttributeError):
        return False


def focus_roblox() -> bool:
    try:
        with _autorelease_pool():
            app = _roblox_app()
            if not app:
                return False
            pid = int(_msg(ctypes.c_int, app, "processIdentifier"))
            if _front_pid() == pid:
                return True
            _msg(ctypes.c_bool, app, "activateWithOptions:", 2, argtypes=(ctypes.c_ulong,))
            deadline = time.monotonic() + 0.2
            while time.monotonic() < deadline:
                if _front_pid() == pid:
                    return True
                time.sleep(0.012)
            return _front_pid() == pid
    except (OSError, AttributeError):
        return False
