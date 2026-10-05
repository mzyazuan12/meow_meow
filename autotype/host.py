"""Keyboard, focus, and the Roblox picture. Works on macOS, Windows, and Linux."""

from __future__ import annotations

import ctypes
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
# Wider than this and a laptop with 8GB starts swapping on every grab.
_FRAME_MAX = 1280


def _fit_frame(width: int, height: int, max_w: int = _FRAME_MAX):
    if width <= max_w or width < 4 or height < 4:
        return 1, width, height
    factor = max(2, (width + max_w - 1) // max_w)
    tw = width // factor
    th = height // factor
    if tw < 2 or th < 2:
        return 1, width, height
    return factor, tw, th


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
    _key_event("\n", 0.012)


def run_capture(stop: threading.Event, on_frame, on_status, name_fn) -> None:
    """Push screen readings until `stop` is set.

    `on_status` receives "up", "down" (Roblox isn't running), or "hidden".
    """
    if sys.platform == "darwin" and _WATCH.is_file() and _CAP.is_file():
        _run_mac_native(stop, on_frame, on_status)
        return
    _run_portable(stop, on_frame, on_status, name_fn)


def _shrink_rgba(raw: bytes, width: int, height: int, max_w: int = _FRAME_MAX):
    """Drop extra pixels so a retina frame is not copied around at full size."""
    factor, tw, th = _fit_frame(width, height, max_w)
    if factor == 1:
        return raw, width, height
    out = bytearray(tw * th * 4)
    stride = width * 4
    step = factor * 4
    for y in range(th):
        src = y * factor * stride
        dst = y * tw * 4
        for x in range(tw):
            i = src + x * step
            out[dst : dst + 4] = raw[i : i + 4]
            dst += 4
    return bytes(out), tw, th


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
    threading.Thread(target=_read_watch, args=(proc, stop, on_frame), daemon=True).start()
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
                time.sleep(0.25)
                continue
            if last != "up":
                last = "up"
                on_status("up")
            try:
                count = width.value * height.value * 4
                if count <= 0 or count > 12_000_000:
                    continue
                # Cast first. free() on the POINTER object itself does not
                # release the pixels, so every grab was kept.
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
            # One small frame at a time. A tight grab loop was the memory spike.
            time.sleep(0.08)
    finally:
        if proc.poll() is None:
            proc.kill()


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


def _run_portable(stop: threading.Event, on_frame, on_status, name_fn) -> None:
    from autotype.tiles import scan_rgba

    last = ""
    while not stop.is_set():
        grabbed = _grab()
        if grabbed is None:
            status = "hidden" if roblox_running() else "down"
            if status != last:
                last = status
                on_status(status)
            time.sleep(0.25)
            continue
        if last != "up":
            last = "up"
            on_status("up")
        raw, width, height = _shrink_rgba(*grabbed)
        del grabbed
        started = time.perf_counter()
        frame = scan_rgba(raw, width, height, name_fn() if name_fn else "")
        frame["ms"] = int((time.perf_counter() - started) * 1000)
        on_frame(frame)
        time.sleep(0.08)


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


def _win_process() -> bool:
    try:
        user32 = ctypes.windll.user32
    except (AttributeError, OSError):
        return False
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if "roblox" in buf.value.lower():
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(visit, 0)
    return bool(found)


def _win_hwnd():
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.lower()
        if "roblox" in title:
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
            found.append((area, hwnd))
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        return None
    found.sort()
    return found[-1][1]


def _win_focus() -> bool:
    try:
        hwnd = _win_hwnd()
    except (AttributeError, OSError):
        return False
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    current = user32.GetForegroundWindow()
    if current == hwnd:
        return True
    fore_thread = user32.GetWindowThreadProcessId(current, None)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(fore_thread, target_thread, True)
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
    user32 = ctypes.windll.user32
    vk, shift = _win_vk(ch)
    if vk is None:
        return
    if shift:
        _win_send(0x10, False)
    _win_send(vk, False)
    if hold:
        time.sleep(hold)
    _win_send(vk, True)
    if shift:
        _win_send(0x10, True)


def _win_vk(ch: str):
    user32 = ctypes.windll.user32
    if ch == "\n":
        return 0x0D, False
    if ch == "\b":
        return 0x08, False
    scanned = user32.VkKeyScanW(ord(ch))
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
    user32 = ctypes.windll.user32
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = 0x0008 | (0x0002 if up else 0)
    input_type = _win_input_type()
    event = input_type()
    event.type = 1
    event.union.ki.wVk = vk
    event.union.ki.wScan = scan
    event.union.ki.dwFlags = flags
    user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))


def _grab_win():
    try:
        hwnd = _win_hwnd()
    except (AttributeError, OSError):
        return None
    if not hwnd:
        return None
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    rect = ctypes.wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
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
    # COLORONCOLOR keeps a hard letter edge. HALFTONE blurs Y into W.
    gdi32.SetStretchBltMode(memory, 3)
    ok = gdi32.StretchBlt(
        memory, 0, 0, dst_w, dst_h,
        desktop, rect.left, rect.top, width, height,
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
    gdi32.GetDIBits(memory, bitmap, 0, dst_h, buf, ctypes.byref(info), 0)
    gdi32.SelectObject(memory, old)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(0, desktop)
    if not ok:
        return None
    # White and black don't care which channel is red. Skip a second copy of the frame.
    return buf.raw, dst_w, dst_h


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


def _linux_process() -> bool:
    proc = Path("/proc")
    if not proc.is_dir():
        return False
    try:
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                comm = (entry / "comm").read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            if "roblox" in comm:
                return True
    except OSError:
        return False
    return False


def _linux_display():
    try:
        x11 = ctypes.CDLL("libX11.so.6")
    except OSError:
        return None, None
    x11.XOpenDisplay.restype = ctypes.c_void_p
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
    x11.XSetInputFocus(display, window, 1, 0)
    x11.XFlush(display)
    x11.XCloseDisplay(display)
    return True


def _linux_window(x11, display):
    root = x11.XDefaultRootWindow(display)
    found = []

    def walk(window):
        name = ctypes.c_char_p()
        x11.XFetchName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_char_p)]
        x11.XFetchName.restype = ctypes.c_int
        if x11.XFetchName(display, window, ctypes.byref(name)) and name.value:
            if b"roblox" in name.value.lower():
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
        x11 = ctypes.CDLL("libX11.so.6")
    except OSError:
        return
    x11.XOpenDisplay.restype = ctypes.c_void_p
    display = x11.XOpenDisplay(None)
    if not display:
        return
    if ch == "\n":
        keysym = 0xFF0D
    elif ch == "\b":
        keysym = 0xFF08
    else:
        keysym = ord(ch.lower())
    x11.XStringToKeysym.restype = ctypes.c_ulong
    code = x11.XKeysymToKeycode(display, keysym)
    if code:
        xtst.XTestFakeKeyEvent(display, code, True, 0)
        x11.XFlush(display)
        if hold:
            time.sleep(hold)
        xtst.XTestFakeKeyEvent(display, code, False, 0)
        x11.XFlush(display)
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
    x11.XGetWindowAttributes(display, window, ctypes.byref(attrs))
    width, height = attrs.width, attrs.height
    if width < 200 or height < 200:
        x11.XCloseDisplay(display)
        return None
    x11.XGetImage.restype = ctypes.c_void_p
    image = x11.XGetImage(display, window, 0, 0, width, height, 0xFFFFFFFF, 2)
    if not image:
        x11.XCloseDisplay(display)
        return None
    # XImage layout: data pointer sits after a few words. Read width*height*4 from XImage.data.
    # Offset of `data` is stable enough on 64-bit libX11 (after width, height, xoffset, format, byte_order, bitmap_unit, bitmap_bit_order, bitmap_pad, depth, bytes_per_line, bits_per_pixel).
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
    bpp = max(info.bits_per_pixel // 8, 4)
    factor, tw, th = _fit_frame(width, height)
    out = bytearray(tw * th * 4)
    for y in range(th):
        src = y * factor * row
        for x in range(tw):
            pixel = src + x * factor * bpp
            base = ctypes.addressof(info.data.contents) + pixel
            bgra = ctypes.string_at(base, 4)
            i = (y * tw + x) * 4
            out[i] = bgra[2]
            out[i + 1] = bgra[1]
            out[i + 2] = bgra[0]
            out[i + 3] = 255
    x11.XDestroyImage(image)
    x11.XCloseDisplay(display)
    return bytes(out), tw, th
