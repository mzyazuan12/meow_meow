from __future__ import annotations

import os
import sys
from pathlib import Path

GRID = 16
CELLS = GRID * GRID

_TEMPLATES: list[list[list[float]]] = []
_TNORM: list[list[float]] = []
_PHRASE = "type an english word"
_TURN_MARK = "starting"
_PHRASE_BITS: list[tuple[int, int, bytes]] = []

def _font_files() -> list[Path]:
    found: list[Path] = []
    if sys.platform == "win32":
        root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        names = ["arialbd.ttf", "ariblk.ttf", "segoeuib.ttf", "calibrib.ttf", "arial.ttf"]
        found.extend(root / name for name in names)
    elif sys.platform == "darwin":
        roots = [
            Path("/System/Library/Fonts/Supplemental"),
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
        ]
        names = [
            "Arial Bold.ttf",
            "Arial Rounded Bold.ttf",
            "Arial.ttf",
            "Avenir.ttc",
            "GillSans.ttc",
        ]
        for root in roots:
            found.extend(root / name for name in names)
    else:
        found.extend(
            [
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
                Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
            ]
        )
    return [path for path in found if path.is_file()]

def _density(raw: bytes, width: int, height: int, stride: int) -> list[float]:
    grid = [0.0] * CELLS
    minx, miny, maxx, maxy = width, height, -1, -1
    for y in range(height):
        row = y * width * stride
        for x in range(width):
            i = row + x * stride
            if raw[i] >= 150 or raw[i + 1] >= 150 or raw[i + 2] >= 150:
                continue
            if x < minx:
                minx = x
            if x > maxx:
                maxx = x
            if y < miny:
                miny = y
            if y > maxy:
                maxy = y
    if maxx < minx:
        return grid
    bw = maxx - minx + 1
    bh = maxy - miny + 1
    side = bw if bw > bh else bh
    ox = minx - (side - bw) // 2
    oy = miny - (side - bh) // 2
    for gy in range(GRID):
        sy = oy + gy * side // GRID
        sy1 = oy + (gy + 1) * side // GRID
        if sy1 <= sy:
            sy1 = sy + 1
        for gx in range(GRID):
            sx = ox + gx * side // GRID
            sx1 = ox + (gx + 1) * side // GRID
            if sx1 <= sx:
                sx1 = sx + 1
            ink = 0
            tot = 0
            for y in range(sy, sy1):
                if y < 0 or y >= height:
                    continue
                row = y * width * stride
                for x in range(sx, sx1):
                    if x < 0 or x >= width:
                        continue
                    tot += 1
                    i = row + x * stride
                    if raw[i] < 150 and raw[i + 1] < 150 and raw[i + 2] < 150:
                        ink += 1
            grid[gy * GRID + gx] = (ink / tot) if tot else 0.0
    return grid

def _norm(grid: list[float]) -> float:
    return sum(v * v for v in grid) ** 0.5

def _ensure_templates() -> None:
    if _TEMPLATES:
        return
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return
    for path in _font_files():
        if len(_TEMPLATES) >= 6:
            break
        try:
            font = ImageFont.truetype(str(path), 120)
        except OSError:
            continue
        for lower in (False, True):
            if len(_TEMPLATES) >= 6:
                break
            pack: list[list[float]] = []
            norms: list[float] = []
            for index in range(26):
                ch = chr((ord("a") if lower else ord("A")) + index)
                image = Image.new("RGB", (180, 180), "white")
                draw = ImageDraw.Draw(image)
                draw.text((30, 20), ch, fill="black", font=font)
                grid = _density(image.tobytes(), 180, 180, 3)
                pack.append(grid)
                norms.append(_norm(grid))
            _TEMPLATES.append(pack)
            _TNORM.append(norms)
        try:
            phrase_font = ImageFont.truetype(str(path), 28)
        except OSError:
            phrase_font = None
        if phrase_font is not None and len(_PHRASE_BITS) < 3:
            image = Image.new("L", (420, 48), 0)
            draw = ImageDraw.Draw(image)
            draw.text((4, 6), _PHRASE, fill=255, font=phrase_font)
            _PHRASE_BITS.append((420, 48, image.tobytes()))

def _cosine(tile: list[float], tmpl: list[float], tnorm: float) -> float:
    dot = 0.0
    norm = 0.0
    for a, b in zip(tile, tmpl):
        dot += a * b
        norm += a * a
    if norm < 1e-6 or tnorm < 1e-6:
        return 0.0
    return dot / ((norm ** 0.5) * tnorm)

def settle_qo(raw: bytes, width: int, height: int, stride: int, guess: str) -> str:

    if guess not in ("q", "o") or width < 8 or height < 8 or stride < 3:
        return guess
    minx, miny, maxx, maxy = width, height, -1, -1
    for y in range(height):
        row = y * width * stride
        for x in range(width):
            i = row + x * stride
            if raw[i] >= 150 or raw[i + 1] >= 150 or raw[i + 2] >= 150:
                continue
            if x < minx:
                minx = x
            if x > maxx:
                maxx = x
            if y < miny:
                miny = y
            if y > maxy:
                maxy = y
    if maxx < minx:
        return guess
    bw = maxx - minx + 1
    bh = maxy - miny + 1
    if bw < 8 or bh < 8:
        return guess
    need = bh // 10
    if need < 2:
        need = 2
    got = 0
    total = 0
    acc = 0
    for y in range(maxy, miny - 1, -1):
        row = y * width * stride
        count = 0
        summed = 0
        for x in range(minx, maxx + 1):
            i = row + x * stride
            if raw[i] < 150 and raw[i + 1] < 150 and raw[i + 2] < 150:
                count += 1
                summed += x
        if not count:
            continue
        got += 1
        total += count
        acc += summed
        if got >= need:
            break
    if total < 3:
        return guess
    rel = (acc / total - minx) / bw
    if rel >= 0.54:
        return "q"
    if rel <= 0.53:
        return "o"
    return guess

def _classify(raw: bytes, width: int, height: int, stride: int) -> str:
    _ensure_templates()
    if not _TEMPLATES:
        return ""
    tile = _density(raw, width, height, stride)
    best = 0.0
    second = 0.0
    letter = ""
    for pack, norms in zip(_TEMPLATES, _TNORM):
        top = -1.0
        nxt = -1.0
        top_i = 0
        for index, (tmpl, tnorm) in enumerate(zip(pack, norms)):
            score = _cosine(tile, tmpl, tnorm)
            if score > top:
                nxt = top
                top = score
                top_i = index
            elif score > nxt:
                nxt = score
        if top > best:
            best = top
            second = nxt
            letter = chr(ord("a") + top_i)
        if best >= 0.9 and best - second >= 0.04:
            break
    if letter in ("q", "o") and best >= 0.62:
        return settle_qo(raw, width, height, stride, letter)
    if best >= 0.62 and best - second >= 0.03:
        return letter
    return ""

def _is_white(raw: bytes, i: int) -> bool:
    r = raw[i]
    g = raw[i + 1]
    b = raw[i + 2]
    hi = r if r > g else g
    if b > hi:
        hi = b
    lo = r if r < g else g
    if b < lo:
        lo = b
    return lo > 198 and hi - lo < 40

def _components(mask: bytearray, width: int, height: int) -> list[tuple[int, int, int, int, int]]:
    parent: list[int] = []

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    runs: list[tuple[int, int, int, int]] = []
    prev: list[tuple[int, int, int]] = []
    for y in range(height):
        row = y * width
        x = 0
        line: list[tuple[int, int, int]] = []
        while x < width:
            if not mask[row + x]:
                x += 1
                continue
            x0 = x
            x += 1
            while x < width and mask[row + x]:
                x += 1
            cid = len(parent)
            parent.append(cid)
            for px0, px1, pid in prev:
                if px1 <= x0 or px0 >= x:
                    continue
                root = find(cid)
                other = find(pid)
                if root != other:
                    parent[other] = root
            line.append((x0, x, cid))
            runs.append((y, x0, x, cid))
        prev = line
    boxes: dict[int, list[int]] = {}
    for y, x0, x1, cid in runs:
        root = find(cid)
        box = boxes.get(root)
        if box is None:
            boxes[root] = [x0, y, x1 - 1, y, x1 - x0]
        else:
            if x0 < box[0]:
                box[0] = x0
            if y < box[1]:
                box[1] = y
            if x1 - 1 > box[2]:
                box[2] = x1 - 1
            if y > box[3]:
                box[3] = y
            box[4] += x1 - x0
    return [tuple(box) for box in boxes.values()]

def _crop(raw: bytes, width: int, stride: int, x: int, y: int, w: int, h: int) -> bytes:
    out = bytearray(w * h * stride)
    for row in range(h):
        start = ((y + row) * width + x) * stride
        out[row * w * stride : (row + 1) * w * stride] = raw[start : start + w * stride]
    return bytes(out)

_HEADER_KEY = None
_HEADER_VALUE = ""

def _header_text(raw: bytes, width: int, height: int, stride: int, name: str) -> str:
    global _HEADER_KEY, _HEADER_VALUE
    _ensure_templates()
    if not _font_files():
        return ""
    band_h = max(8, int(height * 0.16))
    acc = 2166136261
    for y in range(0, band_h, 6):
        row = y * width * stride
        for x in range(0, width * stride, 24):
            acc ^= raw[row + x]
            acc = (acc * 16777619) & 0xFFFFFFFF
    key = (acc, name)
    if key == _HEADER_KEY:
        return _HEADER_VALUE
    band_h = max(8, int(height * 0.16))

    step = 1
    sw = width // step
    sh = band_h // step
    if sw < 20 or sh < 8:
        _HEADER_KEY = key
        _HEADER_VALUE = ""
        return ""
    bits = bytearray(sw * sh)
    for y in range(sh):
        sy = y * step
        for x in range(sw):
            sx = x * step
            i = (sy * width + sx) * stride
            if _is_white(raw, i):
                bits[y * sw + x] = 1
    phrase_hit = _text_hit(bits, sw, sh, _TURN_MARK)
    text = ""
    if phrase_hit:
        cleaned = "".join(ch for ch in (name or "").lower() if ch.isalnum())
        name_hit = len(cleaned) >= 3 and _text_hit(bits, sw, sh, cleaned)
        if name_hit:
            text = f"{name}, type an english word starting with:"
        else:
            text = "opponent, type an english word starting with:"
    _HEADER_KEY = key
    _HEADER_VALUE = text
    return text

def _text_line(bits: bytearray, width: int, height: int) -> tuple[int, int] | None:
    rows = [y for y in range(height) if sum(bits[y * width : (y + 1) * width]) > max(8, width // 80)]
    if not rows:
        return None
    start = rows[0]
    best = (rows[0], rows[0], 1)
    prev = rows[0]
    for y in rows[1:]:
        if y > prev + 2:
            start = y
        prev = y
        if y - start > best[1] - best[0]:
            best = (start, y, y - start)
    return best[0], best[1]

def _text_hit(bits: bytearray, width: int, height: int, text: str) -> bool:
    line = _text_line(bits, width, height)
    if line is None:
        return False
    y0, y1 = line
    line_h = y1 - y0 + 1
    if line_h < 8:
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    path = next(iter(_font_files()), None)
    if path is None:
        return False
    best = 0.0
    for size in range(max(12, line_h), line_h + 6, 2):
        try:
            font = ImageFont.truetype(str(path), size)
        except OSError:
            return False
        image = Image.new("L", (max(32, len(text) * size), size + 12), 0)
        ImageDraw.Draw(image).text((0, 2), text, fill=255, font=font)
        bbox = image.getbbox()
        if not bbox:
            continue
        tight = image.crop(bbox)
        raw = tight.tobytes()
        nw, nh = tight.size
        if nw >= width or nh < 4 or y0 + nh > height:
            continue
        ink = [(x, y) for y in range(0, nh, 2) for x in range(0, nw, 2) if raw[y * nw + x] > 180]
        if len(ink) < 8:
            continue
        for x0 in range(0, max(1, width - nw), 3):
            hit = 0
            for x, y in ink:
                if bits[(y0 + y) * width + (x0 + x)]:
                    hit += 1
            score = hit / len(ink)
            if score > best:
                best = score
            if best >= 0.88:
                return True
    return best >= 0.8

def scan_rgba(raw: bytes, width: int, height: int, name: str = "") -> dict:

    if width < 8 or height < 8 or len(raw) < width * height * 4:
        return {"prompt": "", "header": "", "tiles": 0, "ms": 0, "full": False}
    header = _header_text(raw, width, height, 4, name)
    y0 = int(height * 0.04)
    y1 = int(height * 0.74)
    if y1 <= y0 + 8:
        y1 = height
    step = 2 if width >= 700 else 1
    mw = width // step
    mh = (y1 - y0) // step
    mask = bytearray(mw * mh)
    for y in range(mh):
        sy = y0 + y * step
        src = sy * width * 4
        row = y * mw
        for x in range(mw):
            if _is_white(raw, src + x * step * 4):
                mask[row + x] = 1
    scale = width / 900.0
    if scale < 0.65:
        scale = 0.65
    min_side = int(26 * scale) // step
    max_side = int(190 * scale) // step
    if min_side < 8:
        min_side = 8
    tiles = []
    for x0, y0b, x1, y1b, count in _components(mask, mw, mh):
        bw = x1 - x0 + 1
        bh = y1b - y0b + 1
        if bw < min_side or bh < min_side or bw > max_side or bh > max_side:
            continue
        if abs(bw - bh) > bw / 5:
            continue
        fill = count / float(bw * bh)
        if fill < 0.45 or fill > 0.96:
            continue
        tiles.append((x0 * step, y0 + y0b * step, bw * step, bh * step))
    tiles.sort(key=lambda box: box[0])
    row = _best_row(tiles)
    letters = []
    pad = max(step, 2)
    for x, y, w, h in row:

        if w > pad * 4 and h > pad * 4:
            x += pad
            y += pad
            w -= pad * 2
            h -= pad * 2
        crop = _crop(raw, width, 4, x, y, w, h)
        letters.append(_classify(crop, w, h, 4))
    full = bool(row) and all(letters) and len(letters) == len(row)
    prompt = "".join(letters) if full else ""
    if not row:
        full = True
        prompt = ""
    return {"prompt": prompt, "header": header, "tiles": len(row), "ms": 0, "full": full}

def _best_row(tiles: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    best: list[tuple[int, int, int, int]] = []
    best_score = -1.0
    for i, (x, y, w, h) in enumerate(tiles):
        row = [(x, y, w, h)]
        last = x + w
        cy = y + h / 2
        for nx, ny, nw, nh in tiles[i + 1 :]:
            if abs((ny + nh / 2) - cy) > h / 2:
                continue
            if abs(nh - h) > h / 2 or abs(nw - w) > w / 2:
                continue
            gap = nx - last
            if gap < -(w / 4) or gap > w * 1.05:
                break
            row.append((nx, ny, nw, nh))
            last = nx + nw
        score = float(len(row) * len(row) * w * h)
        if score > best_score:
            best_score = score
            best = row
    return best
