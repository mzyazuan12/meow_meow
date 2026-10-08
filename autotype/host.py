from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_WATCH = _ROOT / "llwatch"
_CAP = _ROOT / "llcap.dylib"
_PROCS: list[subprocess.Popen] = []

_FRAME_MAX = 1600

def _fit_frame(width: int, height: int, max_w: int = _FRAME_MAX):
    if width < 4 or height < 4:
        return 1.0, width, height
    factor = max(1.0, width / max_w, height / 1600)
    return factor, max(2, int(width / factor)), max(2, int(height / factor))

def stop_capture() -> None:
    for proc in _PROCS:
        if proc.poll() is None:
            proc.kill()

def roblox_running() -> bool:
    if sys.platform == "darwin":
        from autotype.mac_input import roblox_running as _mac

        return _mac()
    if sys.platform == "win32":
        return _win_process()
    return _linux_process()

def focus_roblox() -> bool:
    if sys.platform == "darwin":
        from autotype.mac_input import focus_roblox as _mac

        return _mac()
    if sys.platform == "win32":
        return _win_focus()
    return _linux_focus()


def roblox_focused() -> bool:
    if sys.platform == "darwin":
        from autotype.mac_input import roblox_focused as _mac
        return _mac()
    if sys.platform == "win32":
        return _win_is_roblox(_win_api()[0].GetForegroundWindow())
    x11, display = _linux_display()
    if not display:
        return False
    try:
        current, revert = ctypes.c_ulong(), ctypes.c_int()
        x11.XGetInputFocus(display, ctypes.byref(current), ctypes.byref(revert))
        return current.value == _linux_window(x11, display)
    finally:
        x11.XCloseDisplay(display)

def tap_key(kind: str, key: str, hold: float = 0.016) -> None:
    if sys.platform == "darwin":
        from autotype.mac_input import tap_key as _mac

        _mac(kind, key, hold)
        return
    if kind == "back":
        _key_event("\b", hold)
        return
    if not key:
        return
    _key_event(key[0], hold)

def press_enter() -> None:
    if sys.platform == "darwin":
        from autotype.mac_input import press_enter as _mac

        _mac()
        return
    _key_event("\n", 0.020)

def keyboard_available() -> bool:
    if sys.platform == "darwin":
        from autotype.mac_input import keyboard_available as mac
        return mac()
    return sys.platform == "win32" or bool(os.environ.get("DISPLAY"))

def request_keyboard_access() -> None:
    if sys.platform == "darwin":
        from autotype.mac_input import request_keyboard_access as mac
        mac()

def run_capture(stop: threading.Event, on_frame, on_status, name_fn, paused_fn=None) -> None:

    try:
        # One reader on every OS. The Mac grabber still uses the native
        # capture helper; letter and header recognition is shared.
        _run_portable(stop, on_frame, on_status, name_fn, paused_fn)
    except (OSError, ImportError, AttributeError) as exc:
        on_status("unsupported")
        on_frame({"prompt": "", "header": "", "tiles": 0, "full": False, "error": str(exc)})

def _shrink_rgba(raw: bytes, width: int, height: int, max_w: int = _FRAME_MAX):
    factor, tw, th = _fit_frame(width, height, max_w)
    if factor == 1:
        return raw, width, height
    from PIL import Image
    image = Image.frombytes("RGBA", (width, height), raw)
    return image.resize((tw, th), Image.Resampling.LANCZOS).tobytes(), tw, th

def _run_mac_native(stop: threading.Event, on_frame, on_status) -> None:
    from autotype.mac_input import roblox_running as mac_running

    proc = subprocess.Popen(
        [str(_WATCH), "--frames"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    _PROCS.append(proc)
    lib = ctypes.CDLL(str(_CAP))
    lib.ll_grab.restype = ctypes.c_int
    lib.ll_grab.argtypes = [
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    libc.free.argtypes = [ctypes.c_void_p]
    last = ""
    try:
        while not stop.is_set() and proc.poll() is None:
            ptr = ctypes.POINTER(ctypes.c_ubyte)()
            width = ctypes.c_int()
            height = ctypes.c_int()
            if not lib.ll_grab(ctypes.byref(ptr), ctypes.byref(width), ctypes.byref(height)):
                status = "hidden" if mac_running() else "down"
                if status != last:
                    last = status
                    on_status(status)
                stop.wait(0.25)
                continue
            if last != "up":
                last = "up"
                on_status("up")
            try:
                count = width.value * height.value * 4
                if count <= 0 or count > 12_000_000:
                    continue

                address = ctypes.cast(ptr, ctypes.c_void_p)
                raw = ctypes.string_at(address, count)
            finally:
                if ptr:
                    libc.free(ctypes.cast(ptr, ctypes.c_void_p))
            raw, tw, th = _shrink_rgba(raw, width.value, height.value)
            payload = struct.pack("<II", tw, th) + raw
            del raw
            try:
                assert proc.stdin is not None
                proc.stdin.write(payload)
                proc.stdin.flush()
            except (BrokenPipeError, OSError):
                return
            del payload
            assert proc.stdout is not None
            line = proc.stdout.readline()
            if not line:
                break
            frame = _parse_frame(line.decode("utf-8", "replace"))
            if frame is not None:
                on_frame(frame)
            stop.wait(0.015)
    finally:
        if proc.poll() is None:
            proc.kill()
        if not stop.is_set():
            on_status("unsupported")

def _read_watch(proc: subprocess.Popen, stop: threading.Event, on_frame) -> None:
    if proc.stdout is None:
        return
    for raw in proc.stdout:
        if stop.is_set():
            break
        frame = _parse_frame(raw.decode("utf-8", "replace"))
        if frame is not None:
            on_frame(frame)

def _parse_frame(line: str):
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 8 or parts[0] != "PROMPT":
        return None
    data = {}
    it = iter(parts)
    for key in it:
        data[key] = next(it, "")
    prompt = data.get("PROMPT", "")
    if prompt == "-":
        prompt = ""
    try:
        ms = int(data.get("MS", "0") or 0)
    except ValueError:
        ms = 0
    try:
        tiles = int(data.get("TILES", "0") or 0)
    except ValueError:
        tiles = 0
    full = data.get("FULL", "1") != "0"
    return {
        "prompt": prompt.lower(),
        "header": data.get("HEADER", ""),
        "ms": ms,
        "tiles": tiles,
        "full": full,
        "error": data.get("ERROR", ""),
    }

def _run_portable(stop: threading.Event, on_frame, on_status, name_fn, paused_fn=None) -> None:
    from autotype.tiles import scan_rgba

    last = ""
    while not stop.is_set():
        if paused_fn and paused_fn():
            stop.wait(0.025)
            continue
        if sys.platform not in ("darwin", "win32") and not os.environ.get("DISPLAY"):
            on_status("unsupported" if roblox_running() else "down")
            stop.wait(0.5)
            continue
        try:
            grabbed = _grab()
        except Exception:
            grabbed = None
        if grabbed is None:
            status = "hidden" if roblox_running() else "down"
            if status != last:
                last = status
                on_status(status)
            stop.wait(0.25)
            continue
        if last != "up":
            last = "up"
            on_status("up")
        captured_at = time.monotonic()
        try:
            raw, width, height = _shrink_rgba(*grabbed)
            del grabbed
            started = time.perf_counter()
            frame = scan_rgba(raw, width, height, name_fn() if name_fn else "")
            frame["ms"] = int((time.perf_counter() - started) * 1000)
            frame["captured_at"] = captured_at
            on_frame(frame)
        except Exception as exc:
            # A malformed/transition frame must not kill capture mid-match.
            on_frame({"prompt": "", "header": "", "tiles": 0, "full": False,
                      "captured_at": captured_at, "capture_error": str(exc)})
        stop.wait(0.015)

def _grab():
    if sys.platform == "win32":
        return _grab_win()
    if sys.platform == "darwin":
        return _grab_mac()
    return _grab_linux()

def _key_event(ch: str, hold: float) -> None:
    if sys.platform == "win32":
        _win_key(ch, hold)
    else:
        _linux_key(ch, hold)

_WIN_APIS = None


def _win_api():
    """Declare pointer-sized handles explicitly (the ctypes default is 32-bit)."""
    global _WIN_APIS
    if _WIN_APIS is not None:
        return _WIN_APIS
    wt = ctypes.wintypes
    user = ctypes.WinDLL("user32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "EnumWindows": ([ctypes.c_void_p, ctypes.c_void_p], wt.BOOL),
        "IsWindowVisible": ([wt.HWND], wt.BOOL),
        "IsIconic": ([wt.HWND], wt.BOOL),
        "GetWindowRect": ([wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
        "GetClientRect": ([wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
        "ClientToScreen": ([wt.HWND, ctypes.POINTER(wt.POINT)], wt.BOOL),
        "GetWindowThreadProcessId": ([wt.HWND, ctypes.POINTER(wt.DWORD)], wt.DWORD),
        "GetForegroundWindow": ([], wt.HWND),
        "AttachThreadInput": ([wt.DWORD, wt.DWORD, wt.BOOL], wt.BOOL),
        "ShowWindow": ([wt.HWND, ctypes.c_int], wt.BOOL),
        "SetForegroundWindow": ([wt.HWND], wt.BOOL),
        "GetDC": ([wt.HWND], wt.HDC),
        "ReleaseDC": ([wt.HWND, wt.HDC], ctypes.c_int),
        "VkKeyScanW": ([wt.WCHAR], ctypes.c_short),
        "MapVirtualKeyW": ([wt.UINT, wt.UINT], wt.UINT),
        "SendInput": ([wt.UINT, ctypes.c_void_p, ctypes.c_int], wt.UINT),
    }
    for name, (args, ret) in signatures.items():
        fn = getattr(user, name)
        fn.argtypes, fn.restype = args, ret
    for name, args, ret in (
        ("CreateCompatibleDC", [wt.HDC], wt.HDC),
        ("CreateCompatibleBitmap", [wt.HDC, ctypes.c_int, ctypes.c_int], wt.HBITMAP),
        ("SelectObject", [wt.HDC, wt.HANDLE], wt.HANDLE),
        ("DeleteObject", [wt.HANDLE], wt.BOOL),
        ("DeleteDC", [wt.HDC], wt.BOOL),
        ("SetStretchBltMode", [wt.HDC, ctypes.c_int], ctypes.c_int),
        ("StretchBlt", [wt.HDC] + [ctypes.c_int]*4 + [wt.HDC] + [ctypes.c_int]*4 + [wt.DWORD], wt.BOOL),
        ("GetDIBits", [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT], ctypes.c_int),
    ):
        fn = getattr(gdi, name)
        fn.argtypes, fn.restype = args, ret
    kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel.OpenProcess.restype = wt.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wt.BOOL
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    kernel.CloseHandle.restype = wt.BOOL
    try:
        user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        user.SetProcessDPIAware()
    _WIN_APIS = user, gdi, kernel
    return _WIN_APIS


def _win_is_roblox(hwnd) -> bool:
    user, _, kernel = _win_api()
    pid = ctypes.wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return False
    try:
        path = ctypes.create_unicode_buffer(32768)
        length = ctypes.wintypes.DWORD(len(path))
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
            return False
        name = path.value.replace("\\", "/").rsplit("/", 1)[-1].lower()
        return name in ("robloxplayerbeta.exe", "robloxplayer.exe") or (
            name == "windows10universal.exe" and "roblox" in path.value.lower())
    finally:
        kernel.CloseHandle(handle)


def _win_process() -> bool:
    # Include minimized windows when reporting whether the player is running.
    return bool(_win_hwnd(visible=False))


def _win_hwnd(*, visible: bool = True):
    user, _, _ = _win_api()
    found = []
    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.c_void_p)
    def visit(hwnd, _lp):
        if visible and (not user.IsWindowVisible(hwnd) or user.IsIconic(hwnd)):
            return True
        if not _win_is_roblox(hwnd):
            return True
        rect = ctypes.wintypes.RECT()
        if user.GetClientRect(hwnd, ctypes.byref(rect)):
            area = max(0, rect.right-rect.left)*max(0, rect.bottom-rect.top)
            found.append((area, hwnd))
        return True
    user.EnumWindows(visit, 0)
    return max(found, default=(0, None))[1]

def _win_focus() -> bool:
    try:
        hwnd = _win_hwnd()
    except (AttributeError, OSError):
        return False
    if not hwnd:
        return False
    user32 = _win_api()[0]
    current = user32.GetForegroundWindow()
    if current == hwnd:
        return True
    fore_thread = user32.GetWindowThreadProcessId(current, None)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(fore_thread, target_thread, True)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(fore_thread, target_thread, False)
    deadline = time.time() + 0.2
    while time.time() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.012)
    return user32.GetForegroundWindow() == hwnd

def _win_key(ch: str, hold: float) -> None:
    user32 = _win_api()[0]
    vk, shift = _win_vk(ch)
    if vk is None:
        raise ValueError(f"Keyboard layout cannot type {ch!r}")
    if shift:
        _win_send(0x10, False)
    _win_send(vk, False)
    if hold:
        time.sleep(hold)
    _win_send(vk, True)
    if shift:
        _win_send(0x10, True)

def _win_vk(ch: str):
    user32 = _win_api()[0]
    if ch == "\n":
        return 0x0D, False
    if ch == "\b":
        return 0x08, False
    scanned = user32.VkKeyScanW(ch)
    if scanned == -1:
        return None, False
    return scanned & 0xFF, bool(scanned & 0x100)

_WIN_INPUT = None

def _win_input_type():
    global _WIN_INPUT
    if _WIN_INPUT is not None:
        return _WIN_INPUT

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.c_ulong),
            ("wParamL", ctypes.c_ushort),
            ("wParamH", ctypes.c_ushort),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]

    _WIN_INPUT = INPUT
    return INPUT

def _win_send(vk: int, up: bool) -> None:
    user32 = _win_api()[0]
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = 0x0008 | (0x0002 if up else 0)
    input_type = _win_input_type()
    event = input_type()
    event.type = 1
    event.union.ki.wVk = vk
    event.union.ki.wScan = scan
    event.union.ki.dwFlags = flags
    if user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
        raise OSError(ctypes.get_last_error(), "Windows couldn't send a key to Roblox")

def _grab_win():
    try:
        hwnd = _win_hwnd()
    except (AttributeError, OSError):
        return None
    if not hwnd:
        return None
    user32 = _win_api()[0]
    gdi32 = _win_api()[1]
    rect = ctypes.wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = ctypes.wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width < 200 or height < 200:
        return None
    _factor, dst_w, dst_h = _fit_frame(width, height)
    desktop = user32.GetDC(0)
    memory = gdi32.CreateCompatibleDC(desktop)
    bitmap = gdi32.CreateCompatibleBitmap(desktop, dst_w, dst_h)
    old = gdi32.SelectObject(memory, bitmap)

    gdi32.SetStretchBltMode(memory, 3)
    ok = gdi32.StretchBlt(
        memory, 0, 0, dst_w, dst_h,
        desktop, origin.x, origin.y, width, height,
        0x00CC0020,
    )
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32),
            ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32),
            ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16),
            ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32),
            ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.biWidth = dst_w
    info.biHeight = -dst_h
    info.biPlanes = 1
    info.biBitCount = 32
    info.biCompression = 0
    buf = ctypes.create_string_buffer(dst_w * dst_h * 4)
    # GetDIBits requires the bitmap to be deselected first.
    gdi32.SelectObject(memory, old)
    rows = gdi32.GetDIBits(memory, bitmap, 0, dst_h, buf, ctypes.byref(info), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(0, desktop)
    if not ok or rows != dst_h:
        return None
    from PIL import Image
    return Image.frombytes("RGBA", (dst_w, dst_h), buf.raw, "raw", "BGRA").tobytes(), dst_w, dst_h

def _grab_mac():
    if not _CAP.is_file():
        return None
    lib = ctypes.CDLL(str(_CAP))
    lib.ll_grab.restype = ctypes.c_int
    lib.ll_grab.argtypes = [
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    libc.free.argtypes = [ctypes.c_void_p]
    ptr = ctypes.POINTER(ctypes.c_ubyte)()
    width = ctypes.c_int()
    height = ctypes.c_int()
    if not lib.ll_grab(ctypes.byref(ptr), ctypes.byref(width), ctypes.byref(height)):
        return None
    try:
        count = width.value * height.value * 4
        return ctypes.string_at(ptr, count), width.value, height.value
    finally:
        libc.free(ptr)

def _linux_player_pid(pid: int) -> bool:
    try:
        name = (Path("/proc") / str(pid) / "comm").read_text(encoding="utf-8", errors="replace").strip().lower()
    except OSError:
        return False
    return name == "roblox" or name.startswith("robloxplayer") or name == "sober"


def _linux_process() -> bool:
    proc = Path("/proc")
    if not proc.is_dir():
        return False
    try:
        return any(_linux_player_pid(int(entry.name)) for entry in proc.iterdir() if entry.name.isdigit())
    except OSError:
        return False


@ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
def _x_error(display, event):
    # Windows can disappear between enumeration and capture. Do not let Xlib's
    # default error handler terminate the entire app for that race.
    return 0


def _linux_display():
    try:
        x11 = ctypes.CDLL("libX11.so.6")
    except OSError:
        return None, None
    ptr, window = ctypes.c_void_p, ctypes.c_ulong
    signatures = {
        "XOpenDisplay": ([ctypes.c_char_p], ptr),
        "XCloseDisplay": ([ptr], ctypes.c_int),
        "XDefaultRootWindow": ([ptr], window),
        "XFree": ([ptr], ctypes.c_int),
        "XFetchName": ([ptr, window, ctypes.POINTER(ctypes.c_char_p)], ctypes.c_int),
        "XSetInputFocus": ([ptr, window, ctypes.c_int, ctypes.c_ulong], ctypes.c_int),
        "XRaiseWindow": ([ptr, window], ctypes.c_int),
        "XFlush": ([ptr], ctypes.c_int),
        "XKeysymToKeycode": ([ptr, ctypes.c_ulong], ctypes.c_uint),
        "XGetInputFocus": ([ptr, ctypes.POINTER(window), ctypes.POINTER(ctypes.c_int)], ctypes.c_int),
        "XGetWindowAttributes": ([ptr, window, ptr], ctypes.c_int),
        "XGetImage": ([ptr, window, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int], ptr),
        "XDestroyImage": ([ptr], ctypes.c_int),
        "XInternAtom": ([ptr, ctypes.c_char_p, ctypes.c_int], ctypes.c_ulong),
        "XGetWindowProperty": ([ptr, window, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int,
                                ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                ctypes.POINTER(ptr)], ctypes.c_int),
        "XSetErrorHandler": ([ctypes.c_void_p], ctypes.c_void_p),
    }
    for name, (args, ret) in signatures.items():
        fn = getattr(x11, name)
        fn.argtypes, fn.restype = args, ret
    x11.XSetErrorHandler(_x_error)
    display = x11.XOpenDisplay(None)
    return x11, display

def _linux_focus() -> bool:
    x11, display = _linux_display()
    if not display:
        return False
    window = _linux_window(x11, display)
    if not window:
        x11.XCloseDisplay(display)
        return False
    x11.XRaiseWindow(display, window)
    x11.XSetInputFocus(display, window, 1, 0)
    x11.XFlush(display)
    x11.XCloseDisplay(display)
    return True

def _linux_pid(x11, display, window) -> int:
    atom = x11.XInternAtom(display, b"_NET_WM_PID", False)
    kind, count, remaining = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
    fmt, data = ctypes.c_int(), ctypes.c_void_p()
    result = x11.XGetWindowProperty(display, window, atom, 0, 1, False, 6,
                                   ctypes.byref(kind), ctypes.byref(fmt), ctypes.byref(count),
                                   ctypes.byref(remaining), ctypes.byref(data))
    try:
        if result == 0 and data and count.value and fmt.value == 32:
            return int(ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong)).contents.value)
        return 0
    finally:
        if data:
            x11.XFree(data)


def _linux_window(x11, display):
    root = x11.XDefaultRootWindow(display)
    found = []

    def walk(window):
        name = ctypes.c_char_p()
        x11.XFetchName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_char_p)]
        x11.XFetchName.restype = ctypes.c_int
        if x11.XFetchName(display, window, ctypes.byref(name)) and name.value:
            if (b"roblox" in name.value.lower() or b"sober" in name.value.lower()) and _linux_player_pid(_linux_pid(x11, display, window)):
                found.append(window)
            x11.XFree(name)
        kids = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint()
        parent = ctypes.c_ulong()
        ignore = ctypes.c_ulong()
        x11.XQueryTree.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
            ctypes.POINTER(ctypes.c_uint),
        ]
        if x11.XQueryTree(display, window, ctypes.byref(ignore), ctypes.byref(parent), ctypes.byref(kids), ctypes.byref(count)):
            for index in range(count.value):
                walk(kids[index])
            if kids:
                x11.XFree(kids)

    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XFree.argtypes = [ctypes.c_void_p]
    walk(root)
    return found[0] if found else 0

def _linux_key(ch: str, hold: float) -> None:
    try:
        xtst = ctypes.CDLL("libXtst.so.6")
        xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        xtst.XTestFakeKeyEvent.restype = ctypes.c_int
        x11, display = _linux_display()
    except OSError as exc:
        raise OSError("X11 keyboard control is unavailable") from exc
    if not display:
        raise OSError("An X11 display is required for keyboard control")
    if ch == "\n":
        keysym = 0xFF0D
    elif ch == "\b":
        keysym = 0xFF08
    else:
        keysym = ord(ch.lower())
    x11.XStringToKeysym.restype = ctypes.c_ulong
    code = x11.XKeysymToKeycode(display, keysym)
    try:
        if not code or not xtst.XTestFakeKeyEvent(display, code, True, 0):
            raise OSError("X11 couldn't send a key to Roblox")
        x11.XFlush(display)
        try:
            if hold:
                time.sleep(hold)
        finally:
            xtst.XTestFakeKeyEvent(display, code, False, 0)
            x11.XFlush(display)
    finally:
        x11.XCloseDisplay(display)

def _grab_linux():
    try:
        return _grab_linux_image()
    except Exception:
        return None

def _grab_linux_image():
    x11, display = _linux_display()
    if not display:
        return None
    window = _linux_window(x11, display)
    if not window:
        x11.XCloseDisplay(display)
        return None

    class XWindowAttributes(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_int),
            ("y", ctypes.c_int),
            ("width", ctypes.c_int),
            ("height", ctypes.c_int),
            ("border_width", ctypes.c_int),
            ("depth", ctypes.c_int),
            ("visual", ctypes.c_void_p),
            ("root", ctypes.c_ulong),
            ("class", ctypes.c_int),
            ("bit_gravity", ctypes.c_int),
            ("win_gravity", ctypes.c_int),
            ("backing_store", ctypes.c_int),
            ("backing_planes", ctypes.c_ulong),
            ("backing_pixel", ctypes.c_ulong),
            ("save_under", ctypes.c_int),
            ("colormap", ctypes.c_ulong),
            ("map_installed", ctypes.c_int),
            ("map_state", ctypes.c_int),
            ("all_event_masks", ctypes.c_long),
            ("your_event_mask", ctypes.c_long),
            ("do_not_propagate_mask", ctypes.c_long),
            ("override_redirect", ctypes.c_int),
            ("screen", ctypes.c_void_p),
        ]

    attrs = XWindowAttributes()
    if not x11.XGetWindowAttributes(display, window, ctypes.byref(attrs)) or attrs.map_state != 2:
        x11.XCloseDisplay(display)
        return None
    width, height = attrs.width, attrs.height
    if width < 200 or height < 200:
        x11.XCloseDisplay(display)
        return None
    x11.XGetImage.restype = ctypes.c_void_p
    image = x11.XGetImage(display, window, 0, 0, width, height, 0xFFFFFFFF, 2)
    if not image:
        x11.XCloseDisplay(display)
        return None

    class XImage(ctypes.Structure):
        _fields_ = [
            ("width", ctypes.c_int),
            ("height", ctypes.c_int),
            ("xoffset", ctypes.c_int),
            ("format", ctypes.c_int),
            ("data", ctypes.POINTER(ctypes.c_char)),
            ("byte_order", ctypes.c_int),
            ("bitmap_unit", ctypes.c_int),
            ("bitmap_bit_order", ctypes.c_int),
            ("bitmap_pad", ctypes.c_int),
            ("depth", ctypes.c_int),
            ("bytes_per_line", ctypes.c_int),
            ("bits_per_pixel", ctypes.c_int),
        ]

    info = ctypes.cast(image, ctypes.POINTER(XImage)).contents
    row = info.bytes_per_line
    bpp = info.bits_per_pixel // 8
    if bpp not in (3, 4):
        x11.XDestroyImage(image)
        x11.XCloseDisplay(display)
        return None
    factor, tw, th = _fit_frame(width, height)
    out = bytearray(tw * th * 4)
    for y in range(th):
        src = int(y * factor) * row
        for x in range(tw):
            pixel = src + int(x * factor) * bpp
            base = ctypes.addressof(info.data.contents) + pixel
            bgra = ctypes.string_at(base, bpp)
            i = (y * tw + x) * 4
            out[i] = bgra[2]
            out[i + 1] = bgra[1]
            out[i + 2] = bgra[0]
            out[i + 3] = 255
    x11.XDestroyImage(image)
    x11.XCloseDisplay(display)
    return bytes(out), tw, th
