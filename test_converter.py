"""converter モジュールのユニットテスト。"""

import unittest

from ascii_player.converter import (
    HALFBLOCK_CHARS,
    ColorMapper,
    apply_brightness_contrast,
    halfblock_index,
    luminance,
    make_char_table,
    rgb_to_16,
    rgb_to_256,
)


class TestLuminance(unittest.TestCase):
    def test_white_is_max(self):
        self.assertAlmostEqual(luminance(255, 255, 255), 255.0, places=3)

    def test_black_is_zero(self):
        self.assertEqual(luminance(0, 0, 0), 0.0)

    def test_rec709_coefficients(self):
        # Y = 0.2126R + 0.7152G + 0.0722B
        self.assertAlmostEqual(luminance(255, 0, 0), 0.2126 * 255, places=3)
        self.assertAlmostEqual(luminance(0, 255, 0), 0.7152 * 255, places=3)
        self.assertAlmostEqual(luminance(0, 0, 255), 0.0722 * 255, places=3)

    def test_green_brighter_than_red(self):
        self.assertGreater(luminance(0, 255, 0), luminance(255, 0, 0))


class TestBrightnessContrast(unittest.TestCase):
    def test_default_identity(self):
        self.assertEqual(apply_brightness_contrast(128, 0, 1.0), 128)
        self.assertEqual(apply_brightness_contrast(0, 0, 1.0), 0)
        self.assertEqual(apply_brightness_contrast(255, 0, 1.0), 255)

    def test_brightness_adds(self):
        self.assertEqual(apply_brightness_contrast(100, 10, 1.0), 110)

    def test_brightness_clamps(self):
        self.assertEqual(apply_brightness_contrast(250, 100, 1.0), 255)
        self.assertEqual(apply_brightness_contrast(10, -100, 1.0), 0)

    def test_contrast_scales_around_128(self):
        # 128は不変
        self.assertEqual(apply_brightness_contrast(128, 0, 2.0), 128)
        # 128より暗い値はさらに暗くなる
        self.assertEqual(apply_brightness_contrast(64, 0, 2.0), 0)
        # 128より明るい値はさらに明るくなる
        self.assertEqual(apply_brightness_contrast(192, 0, 2.0), 255)


class TestCharTable(unittest.TestCase):
    def test_bright_to_dark_ordering(self):
        charset = "@%#*+=-:. "
        table = make_char_table(charset)
        # 明るいピクセル → 先頭文字（@）、暗いピクセル → 末尾文字（空白）
        self.assertEqual(table[255], "@")
        self.assertEqual(table[0], " ")
        # 単調性: 輝度が上がるほど文字セットの先頭寄り（明るい）文字になる
        positions = [charset.index(ch) for ch in table]
        for i in range(1, len(positions)):
            self.assertLessEqual(positions[i], positions[i - 1])

    def test_mid_luma(self):
        table = make_char_table("@%#*+=-:. ")
        mid = table[128]
        self.assertIn(mid, "@%#*+=-:. ")

    def test_blocks_set(self):
        table = make_char_table("█▓▒░ ")
        self.assertEqual(table[255], "█")
        self.assertEqual(table[0], " ")


class TestColorMapper(unittest.TestCase):
    def test_truecolor_fg(self):
        cm = ColorMapper("truecolor")
        self.assertEqual(cm.fg(10, 20, 30), "\x1b[38;2;10;20;30m")

    def test_truecolor_bg(self):
        cm = ColorMapper("truecolor")
        self.assertEqual(cm.bg(1, 2, 3), "\x1b[48;2;1;2;3m")

    def test_mono_returns_empty(self):
        cm = ColorMapper("mono")
        self.assertEqual(cm.fg(10, 20, 30), "")
        self.assertEqual(cm.bg(10, 20, 30), "")

    def test_256_format(self):
        cm = ColorMapper("256")
        code = cm.fg(255, 0, 0)
        self.assertRegex(code, r"^\x1b\[38;5;\d+m$")

    def test_basic_format(self):
        cm = ColorMapper("basic")
        code = cm.fg(255, 0, 0)
        self.assertRegex(code, r"^\x1b\[3\d+m$|^\x1b\[9\d+m$")

    def test_cache_reuse(self):
        cm = ColorMapper("truecolor")
        self.assertIs(cm.fg(5, 6, 7), cm.fg(5, 6, 7))

    def test_packed_cache_is_bounded(self):
        # 映像は色が無数にあるため、キャッシュを無制限に貯めると
        # 長時間再生でメモリを食い尽くして途中で落ちる。上限を守ること
        from ascii_player.converter import MAX_COLOR_CACHE

        cm = ColorMapper("truecolor")
        for i in range(MAX_COLOR_CACHE + 5000):
            cm.fg_packed(i % 0xFFFFFF)
        self.assertLessEqual(len(cm._packed_fg), MAX_COLOR_CACHE)

    def test_tuple_cache_is_bounded(self):
        from ascii_player.converter import MAX_COLOR_CACHE

        cm = ColorMapper("truecolor")
        for i in range(MAX_COLOR_CACHE + 5000):
            cm.fg((i >> 16) & 0xFF, (i >> 8) & 0xFF, i & 0xFF)
        self.assertLessEqual(len(cm._cache), MAX_COLOR_CACHE)


class TestRgbQuantization(unittest.TestCase):
    def test_256_range(self):
        for rgb in ((0, 0, 0), (255, 255, 255), (128, 64, 32), (200, 10, 250)):
            self.assertGreaterEqual(rgb_to_256(*rgb), 16)
            self.assertLessEqual(rgb_to_256(*rgb), 255)

    def test_16_range(self):
        for rgb in ((0, 0, 0), (255, 255, 255), (255, 0, 0), (100, 100, 100)):
            self.assertGreaterEqual(rgb_to_16(*rgb), 0)
            self.assertLessEqual(rgb_to_16(*rgb), 15)

    def test_16_black_and_white(self):
        self.assertEqual(rgb_to_16(0, 0, 0), 0)
        self.assertEqual(rgb_to_16(255, 255, 255), 15)

    def test_vectorized_256_matches_scalar(self):
        # ベクトル化パス（renderer）が使う配列版とスカラー版が完全に一致すること
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            self.skipTest("numpy なし")
        from ascii_player.converter import rgb_to_256_array

        vals = list(range(0, 256, 21)) + [0, 1, 7, 8, 47, 48, 114, 115, 154, 155, 194, 195, 234, 235, 254, 255]
        grid = np.array([[a, b, c] for a in vals for b in vals for c in vals], dtype=np.uint8)
        got = rgb_to_256_array(grid)
        for i, (r, g, b) in enumerate(grid.tolist()):
            self.assertEqual(int(got[i]), rgb_to_256(r, g, b), (r, g, b))

    def test_vectorized_16_matches_scalar(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            self.skipTest("numpy なし")
        from ascii_player.converter import rgb_to_16_array

        vals = list(range(0, 256, 21)) + [126, 127, 128, 190, 191, 192, 255]
        grid = np.array([[a, b, c] for a in vals for b in vals for c in vals], dtype=np.uint8)
        got = rgb_to_16_array(grid)
        for i, (r, g, b) in enumerate(grid.tolist()):
            self.assertEqual(int(got[i]), rgb_to_16(r, g, b), (r, g, b))


class TestHalfblock(unittest.TestCase):
    def test_ladder(self):
        # 上も下も暗い → 空白
        self.assertEqual(halfblock_index(0, 0), 0)
        self.assertEqual(HALFBLOCK_CHARS[halfblock_index(0, 0)], " ")
        # 下だけ明るい → ▄
        self.assertEqual(HALFBLOCK_CHARS[halfblock_index(0, 255)], "▄")
        # 上だけ明るい → ▀
        self.assertEqual(HALFBLOCK_CHARS[halfblock_index(255, 0)], "▀")
        # 両方明るい → █
        self.assertEqual(HALFBLOCK_CHARS[halfblock_index(255, 255)], "█")


if __name__ == "__main__":
    unittest.main()