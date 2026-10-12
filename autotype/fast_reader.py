"""Reading the speech boxes that show each player's accepted word."""
from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from pathlib import Path

import numpy as np

from autotype import glyphs, tiles

BUBBLE_PATH = Path(__file__).with_name("bubble_glyphs.npz")
_BUBBLE_TEMPLATES = None
# Speech-box letters are small: a Q's tail is a pixel or two, so O, G and Q
# score within this of each other. Every letter that close is kept.
BUBBLE_CLOSE = 0.07


def bubble_feature(mask):
    return glyphs.head_feature(mask, 0, max(mask.shape))


def bubble_letter(mask):
    """The best letter for a glyph, its score, and every letter about as likely."""
    global _BUBBLE_TEMPLATES
    if _BUBBLE_TEMPLATES is None:
        with np.load(BUBBLE_PATH) as data:
            _BUBBLE_TEMPLATES = str(data["labels"]), data["features"]
    labels, features = _BUBBLE_TEMPLATES
    feature = bubble_feature(mask)
    if feature is None:
        return "", 0.0, ""
    scores = features @ feature
    order = np.argsort(-scores)
    best = float(scores[order[0]])
    near = ""
    for index in order[:24]:
        if scores[index] < best - BUBBLE_CLOSE:
            break
        if labels[index] not in near:
            near += labels[index]
    return labels[order[0]], best, near


def fingerprint(rgb):
    return hashlib.blake2b(np.ascontiguousarray(rgb).tobytes(), digest_size=16).digest()


class BubbleReader:
    """Speech boxes above the avatars, cached by box layout.

    The cache is private to one capture worker. Bubbles are evidence for the
    opponent's word, never added to used words on their own.
    """
    def __init__(self):
        self._bubbles = OrderedDict()
        self._bubble_mask_key = None
        self._bubble_results = []

    def read(self, rgb):
        """Read black text inside complete white speech boxes above avatars."""
        height, width = rgb.shape[:2]
        top, bottom = int(height * .12), int(height * .65)
        region = rgb[top:bottom]
        # Find solid speech-box backgrounds cheaply, then OCR at full resolution.
        white = tiles._white(region[::2, ::2])
        mask_key = fingerprint(white)
        if mask_key == self._bubble_mask_key:
            # Dark letters also alter this mask, so a new word invalidates it.
            return list(self._bubble_results)
        runs, labels, count = tiles.label_runs(white)
        boxes = tiles.component_boxes(runs, labels, count)
        found = []
        for x0, y0, x1, y1, area in boxes.tolist():
            w, h = (x1 - x0) * 2, (y1 - y0) * 2
            if (not 16 <= h <= height * .17 or not 1.5 <= w / h <= 24
                    or area < (x1 - x0) * (y1 - y0) * .55):
                continue
            x0, y0, x1, y1 = x0 * 2, y0 * 2 + top, x1 * 2, y1 * 2 + top
            if x0 <= 2 or x1 >= width - 2 or y0 <= top or y1 >= bottom:
                continue
            crop = rgb[y0 + 2:y1 - 2, x0 + 2:x1 - 2]
            key = fingerprint(crop)
            if key not in self._bubbles:
                self._bubbles[key] = self._bubble_text(crop)
                if len(self._bubbles) > 64:
                    self._bubbles.popitem(last=False)
            text, confidence, options = self._bubbles[key]
            if text:
                found.append(dict(word=text, confidence=confidence, box=(x0, y0, x1, y1),
                                  options=options))
        self._bubble_mask_key, self._bubble_results = mask_key, found
        return list(found)

    @staticmethod
    def _bubble_text(rgb):
        """(best reading, its weakest letter's score, the letters possible at each place)."""
        dark = rgb.max(axis=2) < 135
        runs, labels, count = tiles.label_runs(dark)
        boxes = tiles.component_boxes(runs, labels, count)
        pieces = []
        for index, (x0, y0, x1, y1, area) in enumerate(boxes.tolist()):
            if area < 2 or x0 <= 0 or y0 <= 0 or x1 >= rgb.shape[1] or y1 >= rgb.shape[0]:
                continue
            mask = tiles._component_mask(runs[labels == index], (x0, y0, x1, y1))
            pieces.append([x0, y0, x1, y1, mask])
        if not 2 <= len(pieces) <= 48:
            return "", 0.0, ()
        chars, scores, options = [], [], []
        for box, feature, gap in tiles._line_glyphs(pieces):
            x, y, w, height = box
            char, score, near = bubble_letter(dark[y:y + height, x:x + w])
            # Apostrophes and hyphens aren't in the username alphabet. A
            # stray dash of the box's edge reads as one, so it may be nothing.
            h = max(p[3] for p in pieces) - min(p[1] for p in pieces)
            if box[2] >= box[3] * 2 and box[3] < h * .3:
                char, score, near = "-", 1.0, ("-", "")
            elif box[3] < h * .45 and box[1] < min(p[1] for p in pieces) + h * .25:
                char, score, near = "'", 1.0, ("'", "")
            if gap > 45 or score < .72:
                return "", 0.0, ()
            chars.append(char)
            scores.append(score)
            options.append(tuple(near))
        word = "".join(chars).lower()
        if not re.fullmatch(r"[a-z][a-z'-]{0,44}[a-z]", word):
            return "", 0.0, ()
        return word, min(scores), tuple(options)


def build_bubbles():
    """Bundle local templates once; runtime needs neither fonts nor Roblox files."""
    from PIL import Image, ImageDraw, ImageFont
    labels, rows = [], []
    for directory in glyphs.roblox_font_dirs():
        for name in ("Montserrat-Black.ttf", "Montserrat-Bold.ttf", "BuilderSans-ExtraBold.otf"):
            path = directory / name
            if not path.is_file():
                continue
            for size in (16, 24, 32, 48):
                font = ImageFont.truetype(str(path), size)
                for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'-":
                    im = Image.new("L", (size * 2, size * 2))
                    ImageDraw.Draw(im).text((size // 3, 0), char, font=font, fill=255)
                    box = im.getbbox()
                    if box:
                        labels.append(char.lower())
                        rows.append(bubble_feature(np.asarray(im.crop(box)) > 120))
        if rows:
            break
    if not rows:
        raise OSError("Install Roblox to rebuild the speech-box font templates")
    np.savez_compressed(BUBBLE_PATH, labels="".join(labels), features=np.asarray(rows, np.float32))


if __name__ == "__main__":
    build_bubbles()
