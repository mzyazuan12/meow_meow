"""Read the prompt tiles and the turn header from one RGBA Roblox frame."""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import List, Optional, Tuple

import numpy as np

from autotype import glyphs

Box = Tuple[int, int, int, int]


def label_runs(mask: np.ndarray, eight: bool = False):
    """Connected components of a boolean image, via horizontal runs.

    Returns (runs, labels, count): runs is an (n, 3) array of (y, x0, x1) and
    labels gives each run's component, numbered 0..count-1.
    """
    h, w = mask.shape
    padded = np.zeros((h, w + 2), np.int8)
    padded[:, 1:-1] = mask
    edges = np.diff(padded, axis=1)
    ys, x0 = np.nonzero(edges == 1)
    _ye, x1 = np.nonzero(edges == -1)
    n = len(ys)
    if not n:
        return np.zeros((0, 3), np.int64), np.zeros(0, np.int64), 0
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    starts = np.searchsorted(ys, np.arange(h + 1)).tolist()
    xs0 = x0.tolist()
    xs1 = x1.tolist()
    slack = 1 if eight else 0
    for row in range(1, h):
        a, a_end = starts[row - 1], starts[row]
        b, b_end = starts[row], starts[row + 1]
        while a < a_end and b < b_end:
            if xs0[a] < xs1[b] + slack and xs0[b] < xs1[a] + slack:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra
            if xs1[a] < xs1[b]:
                a += 1
            else:
                b += 1
    roots = [find(i) for i in range(n)]
    _uniq, labels = np.unique(np.asarray(roots), return_inverse=True)
    runs = np.stack([ys, x0, x1], axis=1)
    return runs, labels, int(labels.max()) + 1


def component_boxes(runs: np.ndarray, labels: np.ndarray, count: int) -> np.ndarray:
    """(count, 5) array of x0, y0, x1 (exclusive), y1 (exclusive), area."""
    out = np.zeros((count, 5), np.int64)
    out[:, 0] = np.iinfo(np.int64).max
    out[:, 1] = np.iinfo(np.int64).max
    if not count:
        return out
    np.minimum.at(out[:, 0], labels, runs[:, 1])
    np.minimum.at(out[:, 1], labels, runs[:, 0])
    np.maximum.at(out[:, 2], labels, runs[:, 2])
    np.maximum.at(out[:, 3], labels, runs[:, 0] + 1)
    np.add.at(out[:, 4], labels, runs[:, 2] - runs[:, 1])
    return out


def _component_mask(runs: np.ndarray, box) -> np.ndarray:
    x0, y0, x1, y1 = (int(v) for v in box[:4])
    mask = np.zeros((y1 - y0, x1 - x0), bool)
    for y, a, b in runs.tolist():
        mask[y - y0, a - x0:b - x0] = True
    return mask


# --- prompt tiles --------------------------------------------------------------

def _white(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lo = np.minimum(np.minimum(r, g), b)
    hi = np.maximum(np.maximum(r, g), b)
    return (lo > 198) & ((hi - lo) < 40)


def _dark(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., 0] < 150) & (rgb[..., 1] < 150) & (rgb[..., 2] < 150)


def find_tiles(rgb: np.ndarray) -> List[Box]:
    """Boxes of the white interiors of the tile row, left to right."""
    height, width = rgb.shape[:2]
    y0, y1 = 0, height
    if y1 <= y0 + 8:
        y0, y1 = 0, height
    step = 2 if min(width, height) >= 900 else 1
    band = rgb[y0:y1:step, ::step]
    runs, labels, count = label_runs(_white(band))
    boxes = component_boxes(runs, labels, count)
    # Long words shrink the row. Keep small tiles too; border geometry and
    # glyph evidence below distinguish them from header letter fills.
    short = min(width, height)
    min_side = max(12, int(short * 0.015)) // step
    max_side = max(min_side + 4, int(short * 0.50)) // step
    cand: List[Box] = []
    for bx0, by0, bx1, by1, area in boxes.tolist():
        bw, bh = bx1 - bx0, by1 - by0
        if bw < min_side or bh < min_side or bw > max_side or bh > max_side:
            continue
        if abs(bw - bh) > bw / 5 or area < 0.45 * bw * bh:
            continue
        cand.append((bx0 * step, y0 + by0 * step, bw * step, bh * step))
    # A letter's own white body is a small square inside its tile.
    outer = [b for b in cand if not any(o is not b and _inside(b, o) for o in cand)]
    dark = None
    kept = []
    for box in outer:
        if dark is None:
            dark = _dark(rgb)
        if _tile_border(dark, box):
            kept.append(box)
    kept.sort()
    return _best_row(kept, width, rgb)


def _inside(inner: Box, outer: Box) -> bool:
    cx, cy = inner[0] + inner[2] / 2, inner[1] + inner[3] / 2
    return (outer[0] < cx < outer[0] + outer[2] and outer[1] < cy < outer[1] + outer[3]
            and inner[2] * inner[3] < outer[2] * outer[3])


def _tile_border(dark: np.ndarray, box: Box) -> bool:
    x, y, w, h = box
    height = dark.shape[0]
    inset = max(2, w // 8)
    inner = dark[y + inset:y + h - inset, x + inset:x + w - inset]
    if inner.size and inner.mean() > 0.72:
        return False
    above = dark[max(0, y - 4):y, x:x + w]
    below = dark[y + h:min(height, y + h + 4), x:x + w]
    ring = np.concatenate([above.ravel(), below.ravel()])
    return bool(ring.size) and ring.mean() >= 0.125


def _best_row(tiles: List[Box], width: int, rgb: Optional[np.ndarray] = None) -> List[Box]:
    best: List[Box] = []
    best_score = -1.0
    for i, (x, y, w, h) in enumerate(tiles):
        # Score whole rows, never a more readable suffix of the same row.
        # Otherwise one uncertain letter near the start can make a long word
        # appear shorter and trigger a destructive correction.
        if any(abs((py + ph / 2) - (y + h / 2)) <= h / 2
               and abs(ph - h) <= h / 2 and abs(pw - w) <= w / 2
               and -(w / 4) <= x - (px + pw) <= w * 2.6
               for px, py, pw, ph in tiles[:i]):
            continue
        row = [(x, y, w, h)]
        last = x + w
        cy = y + h / 2
        for nx, ny, nw, nh in tiles[i + 1:]:
            if abs((ny + nh / 2) - cy) > h / 2:
                continue
            if abs(nh - h) > h / 2 or abs(nw - w) > w / 2:
                continue
            gap = nx - last
            if gap < -(w / 4) or gap > w * 2.6:
                break
            if gap > w * 1.05:
                # Preserve the slots of up to two missing white tile bodies.
                # Losing a middle tile must not turn the tail into a new row.
                pitch = w * 1.125
                missing = max(1, min(2, round((gap + w) / pitch) - 1))
                for offset in range(missing):
                    row.append((round(last + w * 0.125 + offset * pitch), y, w, h))
            row.append((nx, ny, nw, nh))
            last = nx + nw
        centre = (row[0][0] + last) / 2
        # Avatar text and controls can form square white components too. A
        # genuine outlined glyph must support the row before its size counts.
        readable = sum(bool(read_letter(rgb, box)) for box in row) if rgb is not None else len(row)
        if not readable:
            continue
        score = readable ** 2 * w * h * (readable / len(row)) ** 3 * (1.15 - abs(centre - width / 2) / max(1, width))
        if score > best_score:
            best_score = score
            best = row
    return best


_LETTER_CACHE: "OrderedDict[bytes, str]" = OrderedDict()


def read_letter(rgb: np.ndarray, box: Box) -> str:
    x, y, w, h = box
    crop = rgb[y:y + h, x:x + w]
    key = hashlib.blake2b(np.ascontiguousarray(crop).tobytes()
                          + bytes((w & 255, h & 255)), digest_size=12).digest()
    hit = _LETTER_CACHE.get(key)
    if hit is not None:
        _LETTER_CACHE.move_to_end(key)
        return hit
    letter = glyphs.read_tile(crop)
    # Any pixel change retries recognition, including an unknown tile. Exact
    # unchanged crops cannot gain information by repeating classification.
    _LETTER_CACHE[key] = letter
    if len(_LETTER_CACHE) > 160:
        _LETTER_CACHE.popitem(last=False)
    return letter


# --- turn header ----------------------------------------------------------------

def _grow(mask: np.ndarray, radius: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(radius):
        nxt = out.copy()
        nxt[1:] |= out[:-1]
        nxt[:-1] |= out[1:]
        nxt[:, 1:] |= out[:, :-1]
        nxt[:, :-1] |= out[:, 1:]
        out = nxt
    return out


def header_glyphs(rgb: np.ndarray) -> List[Tuple[Box, Optional[np.ndarray], int]]:
    """Header characters of the main text line: (box, feature, gap-before).

    The game draws white letters with a dark outline, so each letter's white
    fill is its own blob ringed by dark pixels; clouds and sky never are.
    """
    lines = header_lines(rgb)
    return max(lines, key=len) if lines else []


def header_lines(rgb: np.ndarray) -> List[List[Tuple[Box, Optional[np.ndarray], int]]]:
    lo = rgb.min(axis=2)
    hi = rgb.max(axis=2)
    white = (lo > 170) & ((hi - lo) < 50)
    dark = hi < 110
    runs, labels, count = label_runs(white)
    if not count:
        return []
    boxes = component_boxes(runs, labels, count)
    height, width = white.shape
    max_h = max(8, int(height * 0.6))
    order = np.argsort(labels, kind="stable")
    bounds = np.searchsorted(labels[order], np.arange(count + 1))
    pieces = []
    for index, (x0, y0, x1, y1, area) in enumerate(boxes.tolist()):
        bw, bh = x1 - x0, y1 - y0
        if area < 3 or bh > max_h or bh < 3 or bw > bh * 4 + 4:
            continue
        mask = _component_mask(runs[order[bounds[index]:bounds[index + 1]]], (x0, y0, x1, y1))
        pad = 2
        ex0, ey0 = max(0, x0 - pad), max(0, y0 - pad)
        ex1, ey1 = min(width, x1 + pad), min(height, y1 + pad)
        local = np.zeros((ey1 - ey0, ex1 - ex0), bool)
        local[y0 - ey0:y1 - ey0, x0 - ex0:x1 - ex0] = mask
        ring = _grow(local, 2) & ~local
        # 0.45 keeps thin stems (the l in "english" rings at ~0.54) and still
        # rejects clouds, whose white never sits inside a dark outline.
        if not ring.any() or dark[ey0:ey1, ex0:ex1][ring].mean() < 0.45:
            continue
        pieces.append([x0, y0, x1, y1, mask])
    return [_line_glyphs(line) for line in _group_lines(pieces)]


def _group_lines(pieces: list) -> list:
    # Full-size letters define each line; dots and punctuation then join it.
    pieces.sort(key=lambda p: p[3] - p[1], reverse=True)
    lines: list = []
    for piece in pieces:
        cy = (piece[1] + piece[3]) / 2
        for line in lines:
            reach = (line["y1"] - line["y0"]) * 0.35
            if line["y0"] - reach <= cy <= line["y1"] + reach:
                line["items"].append(piece)
                break
        else:
            lines.append({"y0": piece[1], "y1": piece[3], "items": [piece]})
    out = [line["items"] for line in lines if len(line["items"]) >= 6]
    out.sort(key=lambda items: min(p[1] for p in items))
    return out


def _line_glyphs(items: list) -> List[Tuple[Box, Optional[np.ndarray], int]]:
    items.sort(key=lambda p: p[0])
    merged: list = []
    for piece in items:
        if merged:
            prev = merged[-1]
            overlap = min(piece[2], prev[2]) - max(piece[0], prev[0])
            if overlap >= min(piece[2] - piece[0], prev[2] - prev[0]) * 0.5:
                x0, y0 = min(prev[0], piece[0]), min(prev[1], piece[1])
                x1, y1 = max(prev[2], piece[2]), max(prev[3], piece[3])
                mask = np.zeros((y1 - y0, x1 - x0), bool)
                for p in (prev, piece):
                    mask[p[1] - y0:p[3] - y0, p[0] - x0:p[2] - x0] |= p[4]
                merged[-1] = [x0, y0, x1, y1, mask]
                continue
        merged.append(piece)
    areas = sorted(int(p[4].sum()) for p in merged)
    typical = areas[len(areas) // 2] if areas else 0
    body = [p for p in merged if p[4].sum() >= typical * 0.25] or merged
    top = min(p[1] for p in body)
    bottom = max(p[3] for p in body)
    line_h = max(1, bottom - top)
    out = []
    last = None
    for x0, y0, x1, y1, mask in merged:
        gap = 0 if last is None else x0 - last
        last = x1
        out.append(((x0, y0, x1 - x0, y1 - y0), glyphs.head_feature(mask, y0 - top, line_h), gap * 100 // line_h))
    return out


def read_header(rgb: np.ndarray) -> str:
    """Text of each outlined header line, joined with " | "."""
    t = glyphs.templates()
    texts = []
    for line in header_lines(rgb):
        chars = []
        for index, (_box, feature, gap) in enumerate(line):
            char, score = t.classify_head(feature)
            if index and gap >= 19:
                chars.append(" ")
            chars.append(char if score >= glyphs.HEAD_MIN_SCORE else "?")
        texts.append("".join(chars).strip())
    return " | ".join(text for text in texts if text)


def header_band(rgb: np.ndarray) -> np.ndarray:
    height = rgb.shape[0]
    return rgb[: max(8, int(height * 0.16))]


_HEADER_KEY: Optional[bytes] = None
_HEADER_TEXT = ""


def header_text(rgb: np.ndarray) -> str:
    """Cached by the outlined-text pixels only, so a moving sky never re-reads."""
    global _HEADER_KEY, _HEADER_TEXT
    band = header_band(rgb)
    small = band[::2, ::2]
    lo = small.min(axis=2)
    hi = small.max(axis=2)
    text_px = (lo > 170) & ((hi - lo) < 50) & _grow(hi < 110, 2)
    key = hashlib.blake2b(np.packbits(text_px).tobytes(), digest_size=16).digest()
    if key != _HEADER_KEY:
        _HEADER_KEY = key
        _HEADER_TEXT = read_header(band) if text_px.sum() >= 20 else ""
    return _HEADER_TEXT


def frame_array(raw, width: int, height: int) -> np.ndarray:
    return np.frombuffer(raw, np.uint8, count=width * height * 4).reshape(height, width, 4)[..., :3]


def row_is_clipped(rgb: np.ndarray, row: List[Box]) -> bool:
    if not row:
        return False
    width = rgb.shape[1]
    if row[0][0] <= 3 or row[-1][0] + row[-1][2] >= width - 3:
        return True
    # A cut-off edge tile is no longer square, so find_tiles legitimately
    # excludes it. Look for its remaining white body and border at the expected
    # row pitch before calling the remaining, fully visible tiles a whole word.
    pitch = float(np.median([b[0] - a[0] for a, b in zip(row, row[1:])])) if len(row) > 1 else row[0][2] * 1.125
    dark = None
    for box, direction in ((row[0], -1), (row[-1], 1)):
        x, y, w, h = box
        nx = round(x + direction * pitch)
        if not (nx < 0 < nx + w or nx < width < nx + w):
            continue
        left, right = max(0, nx), min(width, nx + w)
        partial = rgb[y:y + h, left:right]
        if partial.size and _white(partial).mean() > 0.45:
            if dark is None:
                dark = _dark(rgb)
            if _tile_border(dark, (left, y, right - left, h)):
                return True
    return False


def scan_rgba(raw, width: int, height: int, name: str = "") -> dict:
    if width < 8 or height < 8 or len(raw) < width * height * 4:
        return {"prompt": "", "header": "", "tiles": 0, "ms": 0, "full": False}
    rgb = frame_array(raw, width, height)
    header = header_text(rgb)
    row = find_tiles(rgb)
    letters = [read_letter(rgb, box) or "?" for box in row]
    prompt = "".join(letters)
    clipped = row_is_clipped(rgb, row)
    return {"prompt": prompt, "header": header, "tiles": len(row), "ms": 0,
            "full": bool(row) and "?" not in prompt and not clipped,
            "row_complete": bool(row) and not clipped, "row_clipped": clipped}
