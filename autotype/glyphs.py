"""Letter recognition built from the game's own glyphs.

Tiles are matched against crops of real Last Letter tiles (``glyph_tiles.png``);
the turn header is matched against Roblox's bundled UI fonts.  Templates are
stored in ``glyphs.bin`` so neither Pillow nor the fonts are needed at runtime,
and the macOS helper reads the same file, so every platform reads identically.

Run ``python3 -m autotype.glyphs`` to rebuild ``glyphs.bin``.
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

_HERE = Path(__file__).resolve().parent
BIN_PATH = _HERE / "glyphs.bin"
ATLAS_PATH = _HERE / "glyph_tiles.png"
ATLAS_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZEBYUAB"
ATLAS_CELL = 176

TILE_WORK = 48
TILE_GRID = 24
HEAD_GRID = 16
HEAD_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_,:"
HEAD_FONTS = ("Montserrat-Black.ttf", "Montserrat-Bold.ttf", "BuilderSans-ExtraBold.otf")
# The trailing glyphs of each sample are this text, one character per glyph.
# Spaces are gaps, not glyphs, so they are not in the string.
HEADER_SAMPLE_TEXT = "ga2323332,typeanenglishwordstartingwith:"
HEADER_SAMPLES = ("header_sample.png", "header_sample_small.png")

TILE_MIN_SCORE = 0.55
TILE_MIN_MARGIN = 0.02
HEAD_MIN_SCORE = 0.55

_MAGIC = b"LLG1"


def area_resize(img: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
    """Average every source pixel by its exact overlap with each output pixel."""
    return _area_matrix(img.shape[0], out_h) @ img @ _area_matrix(img.shape[1], out_w).T


_AREA_CACHE: dict = {}


def _area_matrix(n_in: int, n_out: int) -> np.ndarray:
    key = (n_in, n_out)
    cached = _AREA_CACHE.get(key)
    if cached is not None:
        return cached
    m = np.zeros((n_out, n_in), np.float32)
    step = n_in / n_out
    for o in range(n_out):
        a = o * step
        b = a + step
        i = int(a)
        while i < n_in and i < b:
            m[o, i] = min(b, i + 1) - max(a, i)
            i += 1
    m /= step
    if len(_AREA_CACHE) > 256:
        _AREA_CACHE.clear()
    _AREA_CACHE[key] = m
    return m


def blur(a: np.ndarray) -> np.ndarray:
    """Separable [1 2 1]/4 blur with zero padding."""
    p = np.pad(a, ((1, 1), (0, 0)))
    a = (p[:-2] + 2 * p[1:-1] + p[2:]) * 0.25
    p = np.pad(a, ((0, 0), (1, 1)))
    return (p[:, :-2] + 2 * p[:, 1:-1] + p[:, 2:]) * 0.25


def _normalize(v: np.ndarray) -> Optional[np.ndarray]:
    v = v.ravel().astype(np.float32)
    v = v - v.mean()
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-6 else None


def ink_of(rgb: np.ndarray) -> np.ndarray:
    """0 for white tile paper, 1 for the black glyph outline."""
    gray = rgb[..., :3].astype(np.float32).mean(axis=2)
    return np.clip((200.0 - gray) / 150.0, 0.0, 1.0)


def _small_components(mask: np.ndarray, eight: bool) -> List[Tuple[List[int], bool]]:
    h, w = mask.shape
    flat = mask.ravel().tolist()
    seen = [False] * (h * w)
    out = []
    steps = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)) if eight else \
        ((-1, 0), (0, -1), (0, 1), (1, 0))
    for start in range(h * w):
        if not flat[start] or seen[start]:
            continue
        seen[start] = True
        stack = [start]
        pixels = []
        edge = False
        while stack:
            cur = stack.pop()
            pixels.append(cur)
            cy, cx = divmod(cur, w)
            if cy == 0 or cx == 0 or cy == h - 1 or cx == w - 1:
                edge = True
            for dy, dx in steps:
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < h and 0 <= nx < w:
                    ni = ny * w + nx
                    if flat[ni] and not seen[ni]:
                        seen[ni] = True
                        stack.append(ni)
        out.append((pixels, edge))
    return out


def tile_feature(rgb: np.ndarray) -> Optional[np.ndarray]:
    """Feature of the glyph inside one tile crop (the tile's white interior box).

    Pieces of the tile's own border/corners touch the crop edge and are dropped,
    so only the letter outline is compared, independent of tile size.
    """
    if rgb.shape[0] < 6 or rgb.shape[1] < 6:
        return None
    work = area_resize(ink_of(rgb), TILE_WORK, TILE_WORK)
    keep = np.zeros(TILE_WORK * TILE_WORK, bool)
    for pixels, edge in _small_components(work > 0.3, True):
        if not edge and len(pixels) >= 4:
            keep[pixels] = True
    keep = keep.reshape(TILE_WORK, TILE_WORK)
    if not keep.any():
        return None
    fringe = keep.copy()
    fringe[1:] |= keep[:-1]
    fringe[:-1] |= keep[1:]
    fringe[:, 1:] |= keep[:, :-1]
    fringe[:, :-1] |= keep[:, 1:]
    glyph = np.where(fringe, work, 0.0).astype(np.float32)
    ys, xs = np.nonzero(keep)
    y0, y1 = max(0, int(ys.min()) - 1), min(TILE_WORK, int(ys.max()) + 2)
    x0, x1 = max(0, int(xs.min()) - 1), min(TILE_WORK, int(xs.max()) + 2)
    bw, bh = x1 - x0, y1 - y0
    side = max(bw, bh)
    square = np.zeros((side, side), np.float32)
    oy, ox = (side - bh) // 2, (side - bw) // 2
    square[oy:oy + bh, ox:ox + bw] = glyph[y0:y1, x0:x1]
    return _normalize(blur(blur(area_resize(square, TILE_GRID, TILE_GRID))))


def head_feature(mask: np.ndarray, top: int, line_h: int) -> Optional[np.ndarray]:
    """Feature of one header character: its fill mask inside a line-height square.

    Keeping the vertical position in the line separates o/O/0, x-height letters
    and descenders, which a tight bounding box would erase.
    """
    h, w = mask.shape
    side = max(line_h, w, 1)
    square = np.zeros((side, side), np.float32)
    oy = max(0, min(side - h, top))
    ox = (side - w) // 2
    square[oy:oy + h, ox:ox + w] = mask[: side - oy, : side - ox]
    return _normalize(blur(area_resize(square, HEAD_GRID, HEAD_GRID)))


class Templates:
    def __init__(self, tile_labels: str, tile: np.ndarray, head_labels: str, head: np.ndarray) -> None:
        self.tile_labels = tile_labels
        self.tile = tile
        self.head_labels = head_labels
        self.head = head
        self._tile_index = np.array([ord(c) - 97 for c in tile_labels], np.int64)
        self._tile_letters = sorted(set(tile_labels))
        self._head_letters = sorted(set(head_labels))
        self._head_index = np.array([self._head_letters.index(c) for c in head_labels], np.int64)

    def classify_tile(self, feature: Optional[np.ndarray]) -> Tuple[str, float, float]:
        if feature is None:
            return "", 0.0, 0.0
        best = np.full(26, -1.0, np.float32)
        np.maximum.at(best, self._tile_index, self.tile @ feature)
        order = np.argsort(-best)
        top, second = float(best[order[0]]), float(best[order[1]])
        return chr(97 + int(order[0])), top, top - second

    def classify_head(self, feature: Optional[np.ndarray]) -> Tuple[str, float]:
        if feature is None:
            return "", 0.0
        best = np.full(len(self._head_letters), -1.0, np.float32)
        np.maximum.at(best, self._head_index, self.head @ feature)
        index = int(best.argmax())
        return self._head_letters[index], float(best[index])


_LOADED: Optional[Templates] = None


def templates() -> Templates:
    global _LOADED
    if _LOADED is None:
        _LOADED = load(BIN_PATH)
    return _LOADED


def read_tile(rgb: np.ndarray) -> str:
    """One lowercase letter, or "" when the glyph isn't clear enough to trust."""
    letter, score, margin = templates().classify_tile(tile_feature(rgb))
    if score < TILE_MIN_SCORE or margin < TILE_MIN_MARGIN:
        return ""
    return letter


# --- template file -----------------------------------------------------------

def save(path: Path, t: Templates) -> None:
    with open(path, "wb") as out:
        out.write(_MAGIC)
        for labels, mat, grid in ((t.tile_labels, t.tile, TILE_GRID), (t.head_labels, t.head, HEAD_GRID)):
            out.write(struct.pack("<II", len(labels), grid * grid))
            out.write(labels.encode("ascii"))
            out.write(np.ascontiguousarray(mat, dtype="<f4").tobytes())


def load(path: Path) -> Templates:
    data = Path(path).read_bytes()
    if data[:4] != _MAGIC:
        raise OSError(f"{path} isn't a glyph template file")
    pos = 4
    parts = []
    for _ in range(2):
        count, cells = struct.unpack_from("<II", data, pos)
        pos += 8
        labels = data[pos:pos + count].decode("ascii")
        pos += count
        mat = np.frombuffer(data, dtype="<f4", count=count * cells, offset=pos).reshape(count, cells)
        pos += count * cells * 4
        parts.append((labels, mat.astype(np.float32)))
    return Templates(parts[0][0], parts[0][1], parts[1][0], parts[1][1])


# --- building (development only: needs Pillow and Roblox's fonts) -------------

def _atlas_tiles() -> List[Tuple[str, np.ndarray]]:
    from PIL import Image

    atlas = np.asarray(Image.open(ATLAS_PATH).convert("RGB"))
    out = []
    for index, letter in enumerate(ATLAS_LETTERS):
        row, col = divmod(index, 8)
        cell = atlas[row * ATLAS_CELL:(row + 1) * ATLAS_CELL, col * ATLAS_CELL:(col + 1) * ATLAS_CELL]
        used = ~((cell[..., 0] == 255) & (cell[..., 1] == 0) & (cell[..., 2] == 255))
        ys, xs = np.nonzero(used)
        out.append((letter.lower(), cell[: ys.max() + 1, : xs.max() + 1]))
    return out


def roblox_font_dirs() -> List[Path]:
    import os
    import sys

    found: List[Path] = []
    if sys.platform == "darwin":
        for root in (Path("/Applications"), Path.home() / "Applications"):
            found.append(root / "Roblox.app" / "Contents" / "Resources" / "content" / "fonts")
    elif sys.platform == "win32":
        for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
            if base:
                versions = Path(base) / "Roblox" / "Versions"
                if versions.is_dir():
                    found.extend(sorted(versions.glob("*/content/fonts"), reverse=True))
    else:
        found.extend(sorted(Path.home().glob(".var/app/org.vinegarhq.Sober/data/sober/*/content/fonts")))
    return [path for path in found if path.is_dir()]


def _render_head(font_path: Path, char: str, size: int):
    """Render white text with a dark stroke, as the game draws its header."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(str(font_path), size)
    # The game's outline is thin; a heavier stroke changes 2/z, d/a and h/n.
    stroke = max(1, int(round(size / 40)))
    text = "dhi" + char + "gy"
    width = size * 8
    image = Image.new("RGB", (width, size * 3), (52, 88, 140))
    ImageDraw.Draw(image).text((size // 2, size // 2), text, font=font, fill=(255, 255, 255),
                               stroke_width=stroke, stroke_fill=(12, 12, 12))
    return np.asarray(image)


def build() -> Templates:
    from autotype.tiles import header_glyphs

    tile_labels, tile_rows = [], []
    for letter, crop in _atlas_tiles():
        for size in (24, 28, 34, 44, 60, 84, 0):
            if size:
                from PIL import Image
                sample = np.asarray(Image.fromarray(crop).resize((size, size), Image.LANCZOS))
            else:
                sample = crop
            feature = tile_feature(sample)
            if feature is not None:
                tile_labels.append(letter)
                tile_rows.append(feature)

    # Real header glyphs, so 2/z, d/a, h/n, o/a and l/i follow the game's
    # actual outlines instead of only a lookalike font.
    from autotype.tiles import header_lines

    head_labels, head_rows = [], []

    for name in HEADER_SAMPLES:
        sample = _HERE / name
        if not sample.is_file():
            continue
        from PIL import Image

        image = np.asarray(Image.open(sample).convert("RGB"))
        lines = header_lines(image)
        glyphs = max(lines, key=len) if lines else []
        glyphs = glyphs[-len(HEADER_SAMPLE_TEXT):]
        if len(glyphs) != len(HEADER_SAMPLE_TEXT):
            raise OSError(f"{name} has {len(glyphs)} glyphs, expected {len(HEADER_SAMPLE_TEXT)}")
        for char, (_box, feature, _gap) in zip(HEADER_SAMPLE_TEXT, glyphs):
            if feature is not None:
                head_labels.append(char.lower())
                head_rows.append(feature)

    fonts = []
    for directory in roblox_font_dirs():
        fonts = [directory / name for name in HEAD_FONTS if (directory / name).is_file()]
        if fonts:
            break
    if not fonts:
        raise OSError("Roblox's fonts weren't found; install Roblox to rebuild glyphs.bin")
    for font in fonts:
        for size in (18, 26, 38, 54):
            for char in HEAD_CHARS:
                glyphs = header_glyphs(_render_head(font, char, size))
                # The rendered context is d, h, i, <char>, g, y; it gives every
                # template the same ascender/descender line box as the header.
                if len(glyphs) != 6:
                    continue
                feature = glyphs[3][1]
                if feature is not None:
                    head_labels.append(char.lower())
                    head_rows.append(feature)
    return Templates("".join(tile_labels), np.asarray(tile_rows, np.float32),
                     "".join(head_labels), np.asarray(head_rows, np.float32))


if __name__ == "__main__":
    built = build()
    save(BIN_PATH, built)
    print(f"{len(built.tile_labels)} tile templates, {len(built.head_labels)} header templates -> {BIN_PATH}")
