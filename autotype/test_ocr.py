"""Prompt and header reading, using the game's own tiles and a real header."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from autotype.host import _shrink_rgba
from autotype.glyphs import _atlas_tiles
from autotype.session import header_is_ours, header_is_turn, speaker_from_header
from autotype.tiles import scan_rgba
from autotype import tiles as tile_reader

_HERE = Path(__file__).resolve().parent
_TILES = {}
for _letter, _crop in _atlas_tiles():
    _TILES.setdefault(_letter, _crop)


def _frame(word: str, width: int = 900, height: int = 600, tile: int = 72) -> Image.Image:
    """A sky-coloured window with a row of the game's real tiles."""
    image = Image.new("RGBA", (width, height), (120, 186, 230, 255))
    draw = ImageDraw.Draw(image)
    gap = max(6, tile // 8)
    row = tile * len(word) + gap * (len(word) - 1)
    x = (width - row) // 2
    y = int(height * 0.36)
    for char in word.lower():
        # The game draws a dark stroke around each white tile.
        draw.rectangle((x - 3, y - 3, x + tile + 3, y + tile + 3), fill=(0, 0, 0, 255))
        glyph = Image.fromarray(_TILES[char]).resize((tile, tile), Image.LANCZOS)
        image.paste(glyph, (x, y))
        x += tile + gap
    return image


def _read(image: Image.Image) -> dict:
    return scan_rgba(image.tobytes(), image.size[0], image.size[1])


class GameGlyphTests(unittest.TestCase):
    def test_every_letter_including_q_o_y_v(self) -> None:
        for tile in (48, 90):
            for word in ("qovy", "abcdef", "ghijkl", "mnopqr", "stuvwx", "yz"):
                result = _read(_frame(word, tile=tile))
                self.assertEqual(result["prompt"], word, (word, tile, result))
                self.assertTrue(result["full"], result)
                self.assertEqual(result["tiles"], len(word))

    def test_resize_covers_landscape_retina_portrait_and_small_windows(self) -> None:
        for width, height in ((640, 480), (1366, 768), (3840, 2160), (1080, 1920)):
            tile = max(36, int(min(width, height) * 0.09))
            image = _frame("qovy", width, height, tile)
            raw, w, h = _shrink_rgba(image.tobytes(), width, height)
            result = scan_rgba(raw, w, h)
            self.assertEqual(result["prompt"], "qovy", (width, height, w, h, result))
            self.assertTrue(result["full"])

    def test_long_word_with_small_tiles_is_read_in_full(self) -> None:
        word = "pneumonoultramicroscopic"
        result = _read(_frame(word, width=1600, height=1000, tile=36))
        self.assertEqual(result["prompt"], word, result)
        self.assertEqual(result["tiles"], len(word))
        self.assertTrue(result["full"])

    def test_uncertain_start_of_long_word_never_becomes_a_complete_tail(self) -> None:
        word = "pneumonoultramicroscopic"
        image = _frame(word, width=1600, height=1000, tile=36)
        original = tile_reader.read_letter
        left = (1600 - (36 * len(word) + 6 * (len(word) - 1))) // 2
        def read(rgb, box):
            return "" if box[0] < left + 6 * 42 else original(rgb, box)
        with patch.object(tile_reader, "read_letter", side_effect=read):
            result = _read(image)
        self.assertEqual(result["prompt"], "?" * 6 + word[6:], result)
        self.assertEqual(result["tiles"], len(word))
        self.assertFalse(result["full"])

    def test_a_missing_tile_keeps_its_place(self) -> None:
        tile, gap = 80, 10
        image = _frame("qovy", tile=tile)
        # Blank the second letter, leaving its white tile and dark border.
        row = tile * 4 + gap * 3
        x = (900 - row) // 2 + tile + gap
        y = int(600 * 0.36)
        ImageDraw.Draw(image).rectangle((x + 14, y + 14, x + tile - 14, y + tile - 14), fill=(255, 255, 255, 255))
        result = _read(image)
        self.assertEqual(result["tiles"], 4, result)
        self.assertEqual(result["prompt"], "q?vy", result)
        self.assertFalse(result["full"])

    def test_a_missing_white_tile_body_does_not_discard_the_word_tail(self) -> None:
        tile, gap = 80, 10
        image = _frame("qovy", tile=tile)
        x = (900 - (tile * 4 + gap * 3)) // 2 + tile + gap
        y = int(600 * .36)
        ImageDraw.Draw(image).rectangle((x - 3, y - 3, x + tile + 3, y + tile + 3), fill=(120, 186, 230, 255))
        result = _read(image)
        self.assertEqual(result["prompt"], "q?vy", result)
        self.assertEqual(result["tiles"], 4)
        self.assertFalse(result["full"])

    def test_real_header_names_the_speaker_and_ignores_menu_icons(self) -> None:
        sample = np.asarray(Image.open(_HERE / "header_sample.png").convert("RGB"))
        height = int(sample.shape[0] / 0.16) + 8
        frame = np.zeros((height, sample.shape[1], 4), np.uint8)
        frame[..., :3] = (120, 186, 230)
        frame[..., 3] = 255
        frame[: sample.shape[0], : sample.shape[1], :3] = sample
        first = scan_rgba(frame.tobytes(), frame.shape[1], frame.shape[0], name="wrong_previous_name")
        second = scan_rgba(frame.tobytes(), frame.shape[1], frame.shape[0], name="ga2323332")
        self.assertEqual(first["header"], second["header"])
        self.assertEqual(speaker_from_header(first["header"]), "ga2323332")
        self.assertTrue(header_is_ours("ga2323332", first["header"]), first["header"])
        self.assertFalse(header_is_ours("someoneelse", first["header"]), first["header"])
        self.assertNotIn("opponent", first["header"])

    def test_no_turn_instruction_never_manufactures_a_turn(self) -> None:
        image = Image.new("RGBA", (900, 600), (120, 186, 230, 255))
        result = _read(image)
        self.assertFalse(header_is_turn(result["header"]))
        self.assertEqual(result["tiles"], 0)
        self.assertEqual(result["prompt"], "")


if __name__ == "__main__":
    unittest.main()
