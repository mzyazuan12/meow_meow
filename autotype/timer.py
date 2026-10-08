"""Read the turn clock and the red rejection banner from one frame.

The clock is a white face ringed in black below the table. Its digits are
outlined like the header, with a cream fill that turns yellow as time runs out,
and a coloured arc drawn clockwise from twelve o'clock shows the fraction of
the turn left. Run ``python3 -m autotype.timer`` to rebuild the digit templates.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from autotype import glyphs
from autotype.tiles import _component_mask, _grow, component_boxes, label_runs

_HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = _HERE / "timer_glyphs.npz"
TIMER_CHARS = "0123456789.s"
TIMER_FONTS = ("FredokaOne-Regular.ttf", "BuilderSans-ExtraBold.otf", "Montserrat-Black.ttf",
               "Montserrat-Bold.ttf")
TIMER_MIN_SCORE = 0.5
ARC_SAMPLES = 120
STAGES = (15.0, 10.0, 7.0, 5.0, 3.0)

_TEMPLATES: Optional[Tuple[str, np.ndarray]] = None


def _channels(rgb: np.ndarray):
    r, g, b = (rgb[..., i].astype(np.int16) for i in range(3))
    return r, g, b, np.minimum(np.minimum(r, g), b), np.maximum(np.maximum(r, g), b)


def _fill_masks(rgb: np.ndarray):
    r, g, b, lo, hi = _channels(rgb)
    light = (lo > 150) | ((r > 180) & (g > 150) & (r - b > 40))
    return light, hi < 120


def _face_white(rgb: np.ndarray) -> np.ndarray:
    r, _g, b, lo, hi = _channels(rgb)
    return (lo > 226) & ((hi - lo) < 26) & ((r - b) < 13)


def _components(light: np.ndarray, dark: np.ndarray, min_area: int, keep=None) -> List[dict]:
    runs, labels, count = label_runs(light)
    boxes = component_boxes(runs, labels, count)
    order = np.argsort(labels, kind="stable")
    bounds = np.searchsorted(labels[order], np.arange(count + 1))
    height, width = light.shape
    out = []
    for index, (x0, y0, x1, y1, area) in enumerate(boxes.tolist()):
        if area < min_area or (keep is not None and not keep((x0, y0, x1, y1))):
            continue
        mask = _component_mask(runs[order[bounds[index]:bounds[index + 1]]], (x0, y0, x1, y1))
        ex0, ey0, ex1, ey1 = max(0, x0 - 2), max(0, y0 - 2), min(width, x1 + 2), min(height, y1 + 2)
        local = np.zeros((ey1 - ey0, ex1 - ex0), bool)
        local[y0 - ey0:y1 - ey0, x0 - ex0:x1 - ex0] = mask
        ring = _grow(local, 2) & ~local
        ringed = float(dark[ey0:ey1, ex0:ex1][ring].mean()) if ring.any() else 0.0
        out.append({"box": (x0, y0, x1, y1), "mask": mask, "ring": ringed})
    return out


def _digit_glyphs(face: np.ndarray) -> List[Tuple[Tuple[int, int, int, int], Optional[np.ndarray]]]:
    """Outlined characters inside a face crop, left to right, with features."""
    height = face.shape[0]
    light, dark = _fill_masks(face)
    pieces = [c for c in _components(light & ~_face_white(face), dark, 3)
              if c["ring"] >= 0.4 and c["box"][0] > 0 and c["box"][1] > 0
              and c["box"][3] - c["box"][1] <= height * 0.6]
    if not pieces:
        return []
    tall = max(c["box"][3] - c["box"][1] for c in pieces)
    # Anti-aliased outlines leave hairline slivers between glyphs.
    pieces = [c for c in pieces if c["box"][3] - c["box"][1] >= tall * 0.15
              and c["box"][2] - c["box"][0] >= max(3, tall * 0.15)]
    digits = [c for c in pieces if c["box"][3] - c["box"][1] >= tall * 0.7]
    top = min(c["box"][1] for c in digits)
    line_h = max(1, max(c["box"][3] for c in digits) - top)
    pieces.sort(key=lambda c: c["box"][0])
    return [(c["box"], glyphs.head_feature(c["mask"], c["box"][1] - top, line_h)) for c in pieces]


def _templates() -> Optional[Tuple[str, np.ndarray]]:
    global _TEMPLATES
    if _TEMPLATES is None and TEMPLATE_PATH.is_file():
        data = np.load(TEMPLATE_PATH)
        _TEMPLATES = (str(data["labels"]), data["features"].astype(np.float32))
    return _TEMPLATES


def _read_digits(face: np.ndarray) -> Optional[float]:
    loaded = _templates()
    if loaded is None:
        return None
    labels, features = loaded
    height = face.shape[0]
    text = ""
    for box, feature in _digit_glyphs(face):
        if abs((box[1] + box[3]) / 2 - height / 2) >= height * 0.3:
            continue
        if feature is None:
            text += "?"
            continue
        scores = features @ feature
        best = int(scores.argmax())
        text += labels[best] if scores[best] >= TIMER_MIN_SCORE else "?"
    if not re.fullmatch(r"\d{1,2}\.\ds?", text):
        return None
    value = float(text.rstrip("s"))
    return value if value <= 20 else None


def _arc_fraction(rgb: np.ndarray, box: Tuple[int, int, int, int]) -> Optional[float]:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    radius = (x1 - x0 + y1 - y0) / 4
    r, g, b, _lo, _hi = _channels(rgb)
    # Cream, yellow and orange arcs; the red carpet and blue-white desk are not.
    arc = (r > 190) & (g > 100) & (r - b >= 14)
    height, width = arc.shape
    angles = np.arange(ARC_SAMPLES) / ARC_SAMPLES * 2 * np.pi
    scales = np.linspace(1.0, 1.45, 10)
    xs = np.rint(cx + np.sin(angles)[:, None] * radius * scales[None, :]).astype(int)
    ys = np.rint(cy - np.cos(angles)[:, None] * radius * scales[None, :]).astype(int)
    inside = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
    hit = np.zeros(xs.shape, bool)
    hit[inside] = arc[ys[inside], xs[inside]]
    hits = hit.any(axis=1).tolist()
    if sum(hits) < 3:
        return None
    runs, index = [], 0
    while index < len(hits):
        if hits[index]:
            start = index
            while index < len(hits) and hits[index]:
                index += 1
            runs.append((start, index))
        else:
            index += 1
    # The bells and hand can hide a few samples; a long gap ends the arc.
    # Specks of other colours past its end are not a continuation.
    end = None
    for start, stop in runs:
        if end is None:
            if start > 6:
                return None
            end = stop
        elif start - end > 6:
            break
        elif stop - start >= 3:
            end = stop
    return end / ARC_SAMPLES if end else None


def read_clock(rgb: np.ndarray) -> dict:
    """{"timer": seconds or None, "timer_frac": fraction left or None}."""
    height, width = rgb.shape[:2]
    rx0, ry0 = int(width * 0.3), int(height * 0.5)
    region = rgb[ry0:int(height * 0.98), rx0:int(width * 0.7)]
    out = {"timer": None, "timer_frac": None}
    if region.size == 0:
        return out
    r, _g, b, lo, hi = _channels(region)
    dark = hi < 120
    white = (lo > 226) & ((hi - lo) < 26) & ((r - b) < 13)
    def face_shaped(box) -> bool:
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        clipped = x0 <= 0 or y0 <= 0 or x1 >= region.shape[1] - 1 or y1 >= region.shape[0] - 1
        return not clipped and height * 0.05 <= bh <= height * 0.35 and 0.7 <= bw / bh <= 1.4

    faces = [comp for comp in _components(white, dark, 30, face_shaped) if comp["ring"] >= 0.3]
    if not faces:
        return out
    face = max(faces, key=lambda c: (c["box"][2] - c["box"][0]) * (c["box"][3] - c["box"][1]))
    x0, y0, x1, y1 = face["box"]
    out["timer"] = _read_digits(region[y0:y1, x0:x1])
    out["timer_frac"] = _arc_fraction(region, face["box"])
    return out


def read_alert(rgb: np.ndarray) -> bool:
    """Whether red outlined banner text ("Already used!") is under the table."""
    height, width = rgb.shape[:2]
    band = rgb[int(height * 0.8):int(height * 0.99), int(width * 0.28):int(width * 0.72)].astype(np.int16)
    if band.size == 0:
        return False
    r, g, b = band[..., 0], band[..., 1], band[..., 2]
    # The banner is pure red; the carpet behind it always carries some green and blue.
    red = (r > 190) & (g < 22) & (b < 26)
    if red.mean() < 0.012:
        return False
    dark = (r < 150) & (g < 40) & (b < 40)
    ring = _grow(red, 2) & ~red
    if not ring.any() or dark[ring].mean() < 0.2:
        return False
    runs, labels, count = label_runs(red)
    boxes = [box for box in component_boxes(runs, labels, count).tolist() if box[4] >= 15]
    if len(boxes) < 5:
        return False
    return max(box[2] for box in boxes) - min(box[0] for box in boxes) >= band.shape[1] * 0.3


class TurnClock:
    """Seconds left in the current turn from digit reads and the shrinking arc.

    A turn lasts 15, 10, 7, 5 or 3 seconds depending on the stage of the match.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.total: Optional[float] = None
        self._estimates: List[float] = []
        self._samples: List[Tuple[float, float]] = []
        self._deadline: Optional[float] = None
        self._deadline_at = 0.0
        self._turn_at: Optional[float] = None
        self._last_frac: Optional[float] = None
        self._last_seconds: Optional[float] = None

    def _new_turn(self) -> None:
        self._samples = []
        self._deadline = None

    def _learn(self, estimate: float) -> None:
        if not 1.0 <= estimate <= 20.0:
            return
        stage = min(STAGES, key=lambda s: abs(s - estimate) / s)
        if abs(stage - estimate) / stage > 0.3:
            return
        self._estimates = (self._estimates + [stage])[-5:]
        self.total = sorted(self._estimates)[len(self._estimates) // 2]

    def observe(self, seconds: Optional[float], frac: Optional[float], at: float) -> None:
        if frac is not None and self._last_frac is not None and frac > self._last_frac + 0.12:
            self._new_turn()
        elif seconds is not None and self._last_seconds is not None and seconds > self._last_seconds + 0.8:
            self._new_turn()
        if frac is not None:
            self._last_frac = frac
            self._samples = [s for s in self._samples if at - s[0] <= 4.0] + [(at, frac)]
            if len(self._samples) >= 4 and self._samples[-1][0] - self._samples[0][0] >= 0.6:
                ts = np.array([s[0] for s in self._samples])
                fs = np.array([s[1] for s in self._samples])
                slope = float(np.polyfit(ts - ts[0], fs, 1)[0])
                if slope < 0:
                    self._learn(-1.0 / slope)
        if seconds is not None:
            self._last_seconds = seconds
            if frac is not None and frac > 0.15:
                self._learn(seconds / frac)
            elif self.total is None:
                self._learn(min((s for s in STAGES if s >= seconds), default=STAGES[0]))
            self._deadline, self._deadline_at = at + seconds, at
        elif frac is not None and self.total is not None:
            self._deadline, self._deadline_at = at + frac * self.total, at

    def start_turn(self, at: float) -> None:
        self._turn_at = at
        if self._deadline is not None and self._deadline_at < at - 0.05:
            self._deadline = None

    def remaining(self, now: float) -> Optional[float]:
        if self._deadline is not None and now - self._deadline_at <= 2.0:
            return self._deadline - now
        if self.total is not None and self._turn_at is not None:
            return self.total - (now - self._turn_at)
        return None


def build() -> Tuple[str, np.ndarray]:
    from PIL import Image, ImageDraw, ImageFont

    fonts = []
    for directory in glyphs.roblox_font_dirs():
        fonts = [directory / name for name in TIMER_FONTS if (directory / name).is_file()]
        if fonts:
            break
    if not fonts:
        raise OSError("Roblox's fonts weren't found; install Roblox to rebuild timer_glyphs.npz")
    labels, rows = [], []
    for font_path in fonts:
        for size in (18, 24, 32, 44, 60):
            font = ImageFont.truetype(str(font_path), size)
            for char in TIMER_CHARS:
                for fill in ((246, 242, 214), (250, 232, 120)):
                    image = Image.new("RGB", (size * 5, size * 2), (255, 255, 255))
                    ImageDraw.Draw(image).text((size // 3, size // 3), "0" + char + "0", font=font,
                                               fill=fill, stroke_width=max(1, size // 16),
                                               stroke_fill=(10, 10, 10))
                    line = _digit_glyphs(np.asarray(image).astype(np.int16))
                    if len(line) == 3 and line[1][1] is not None:
                        labels.append(char)
                        rows.append(line[1][1])
    return "".join(labels), np.asarray(rows, np.float32)


if __name__ == "__main__":
    built_labels, built_rows = build()
    np.savez_compressed(TEMPLATE_PATH, labels=np.array(built_labels), features=built_rows)
    print(f"{len(built_labels)} timer templates -> {TEMPLATE_PATH}")
