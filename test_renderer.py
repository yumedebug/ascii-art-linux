"""renderer モジュールのユニットテスト。"""

import random
import unittest
from unittest import mock

import ascii_player.renderer as renderer_module
from ascii_player.renderer import ASPECT_TOLERANCE, Renderer, compute_pixel_dims


def _solid_bytes(pw: int, ph: int, r: int, g: int, b: int) -> bytes:
    return bytes((r, g, b)) * (pw * ph)


def _random_bytes(pw: int, ph: int, seed: int = 0) -> bytes:
    """決定的な擬似ランダムフレーム（ベクトル化パスとスカラーパスの比較用）。"""
    rng = random.Random(seed)
    return bytes(rng.randrange(256) for _ in range(pw * ph * 3))


def _gradient_bytes(pw: int, ph: int) -> bytes:
    """左が黒・右が白の横方向グレースケールフレーム。"""
    row = bytearray()
    for x in range(pw):
        v = round(x * 255 / max(1, pw - 1))
        row += bytes((v, v, v))
    return bytes(row) * ph


class TestComputePixelDims(unittest.TestCase):
    def test_fixed_4_3_landscape_terminal(self):
        # 80列24行の端末（物理アスペクト1.67 > 4:3）→ 高さ基準で正確な4:3
        pw, ph, lines = compute_pixel_dims(80, 24, "ascii", cell_ratio=2.0)
        self.assertEqual((pw, lines), (64, 24))
        # アスペクト補正: 表示アスペクト = 4:3
        display_aspect = pw / (lines * 2.0)  # 文字セル比で補正
        self.assertAlmostEqual(display_aspect, 4 / 3, delta=0.01)

    def test_halfblock_doubles_height(self):
        pw, ph, lines = compute_pixel_dims(80, 24, "halfblock")
        self.assertEqual(ph, lines * 2)
        self.assertAlmostEqual(pw / (lines * 2.0), 4 / 3, delta=0.01)

    def test_ascii_single_height(self):
        pw, ph, lines = compute_pixel_dims(80, 24, "ascii")
        self.assertEqual(ph, lines)

    def test_override_width_height(self):
        pw, ph, lines = compute_pixel_dims(120, 40, "halfblock", width=60, height=20)
        self.assertLessEqual(pw, 60)
        self.assertLessEqual(lines, 20)
        self.assertEqual(ph, lines * 2)
        self.assertAlmostEqual(pw / (lines * 2.0), 4 / 3, delta=0.01)

    def test_max_limits(self):
        pw, ph, lines = compute_pixel_dims(120, 40, "ascii", max_cols=84, max_rows=26)
        self.assertLessEqual(pw, 84)
        self.assertLessEqual(lines, 26)

    def test_tall_terminal_is_width_limited(self):
        # 40列30行の端末（物理アスペクト0.67 < 4:3）→ 幅基準で4:3に収める
        pw, ph, lines = compute_pixel_dims(40, 30, "ascii", cell_ratio=2.0)
        self.assertEqual(pw, 40)
        display_aspect = pw / (lines * 2.0)
        self.assertAlmostEqual(display_aspect, 4 / 3, delta=0.02)

    def test_width_height_are_clamped_to_terminal(self):
        # 端末より大きい --width/--height を渡してもはみ出さない
        # （はみ出すと端末が折り返し、行間0・全画面表示が崩れる）
        pw, ph, lines = compute_pixel_dims(80, 24, "ascii", width=500, height=100)
        self.assertLessEqual(pw, 80)
        self.assertLessEqual(lines, 24)
        self.assertAlmostEqual(pw / (lines * 2.0), 4 / 3, delta=0.02)

    def test_never_exceeds_terminal_for_any_size(self):
        for cols in range(20, 180, 11):
            for rows in range(5, 50, 7):
                for mode in ("ascii", "blocks", "halfblock"):
                    pw, ph, lines = compute_pixel_dims(cols, rows, mode, cell_ratio=2.0)
                    self.assertLessEqual(pw, cols)
                    self.assertLessEqual(lines, rows)
                    expected_ph = lines * 2 if mode == "halfblock" else lines
                    self.assertEqual(ph, expected_ph)

    def test_aspect_is_always_4_3_within_tolerance(self):
        for cols in range(20, 200, 13):
            for rows in range(10, 60, 3):
                pw, ph, lines = compute_pixel_dims(cols, rows, "ascii", cell_ratio=2.0)
                aspect = pw / (lines * 2.0)
                self.assertAlmostEqual(aspect, 4 / 3, delta=4 / 3 * ASPECT_TOLERANCE + 1e-9)

    def test_uses_full_area_when_4_3_is_exact(self):
        # 100x30 の端末は 80x30 がちょうど4:3 → 端末いっぱいの高さを使う
        pw, ph, lines = compute_pixel_dims(100, 30, "ascii", cell_ratio=2.0)
        self.assertEqual((pw, lines), (80, 30))


class TestRenderAscii(unittest.TestCase):
    def test_mono_bright_frame(self):
        r = Renderer("ascii", "mono")
        pw, ph, _ = compute_pixel_dims(40, 12, "ascii")
        out = r.render(_solid_bytes(pw, ph, 255, 255, 255), pw, ph)
        lines = out.split("\n")
        self.assertEqual(len(lines), ph)
        self.assertEqual(len(lines[0]), pw)
        self.assertNotIn("\x1b[", out)
        self.assertTrue(all(line.startswith("@") for line in lines))

    def test_mono_dark_frame_is_spaces(self):
        r = Renderer("ascii", "mono")
        pw, ph, _ = compute_pixel_dims(40, 12, "ascii")
        out = r.render(_solid_bytes(pw, ph, 0, 0, 0), pw, ph)
        self.assertTrue(all(set(line) == {" "} for line in out.split("\n")))

    def test_color_mode_has_ansi(self):
        r = Renderer("ascii", "truecolor")
        pw, ph, _ = compute_pixel_dims(40, 12, "ascii")
        out = r.render(_solid_bytes(pw, ph, 200, 100, 50), pw, ph)
        self.assertIn("\x1b[38;2;", out)
        # 各セルは 文字1つ+エスケープ
        line = out.split("\n")[0]
        self.assertEqual(len(line.replace("\x1b[38;2;200;100;50m", "")), pw)

    def test_brightness_changes_chars(self):
        r = Renderer("ascii", "mono")
        pw, ph, _ = compute_pixel_dims(40, 12, "ascii")
        mid = _solid_bytes(pw, ph, 128, 128, 128)
        out_default = r.render(mid, pw, ph)
        r.set_brightness_contrast(100, 1.0)
        out_brighter = r.render(mid, pw, ph)
        # 明るくすると先頭寄り（明るい）文字へ変わる
        first_default = out_default.split("\n")[0][0]
        first_brighter = out_brighter.split("\n")[0][0]
        self.assertNotEqual(first_default, first_brighter)
        self.assertLess("@%#*+=-:. ".index(first_brighter), "@%#*+=-:. ".index(first_default))


class TestVectorizedMatchesScalar(unittest.TestCase):
    """numpy のベクトル化パスと numpy なしのスカラーパスが同一出力になること。

    環境に numpy があるかどうかで絵が変わらないことを保証する。
    """

    def _render_both(self, mode, color, brightness, contrast, buf, pw, ph):
        r = Renderer(mode, color, brightness, contrast)
        vectorized = r.render(buf, pw, ph)
        with mock.patch.object(renderer_module, "HAS_NUMPY", False):
            scalar = r.render(buf, pw, ph)
        return vectorized, scalar

    def test_grid_modes_match(self):
        pw, ph = 37, 11
        buf = _random_bytes(pw, ph, seed=5)
        for charset in ("ascii", "blocks"):
            for color in ("mono", "truecolor", "256", "basic"):
                for brightness, contrast in ((0, 1.0), (30, 1.4), (-40, 0.7)):
                    with self.subTest(charset=charset, color=color, br=brightness):
                        vectorized, scalar = self._render_both(
                            charset, color, brightness, contrast, buf, pw, ph
                        )
                        self.assertEqual(vectorized, scalar)

    def test_halfblock_mono_matches(self):
        pw, ph = 40, 20
        buf = _random_bytes(pw, ph, seed=6)
        for brightness, contrast in ((0, 1.0), (30, 1.4), (-40, 0.7)):
            with self.subTest(br=brightness):
                vectorized, scalar = self._render_both(
                    "halfblock", "mono", brightness, contrast, buf, pw, ph
                )
                self.assertEqual(vectorized, scalar)

    def test_blocks_charset_is_not_ascii(self):
        # blocks の █▓▒░ はマルチバイト。ASCII 前提の取り出しで落ちないこと
        r = Renderer("blocks", "mono")
        buf = _solid_bytes(8, 4, 255, 255, 255)
        out = r.render(buf, 8, 4).split("\n")
        self.assertEqual(len(out), 4)
        self.assertTrue(all(line == "█" * 8 for line in out))


class TestHighDensityAsciiOutput(unittest.TestCase):
    """高密度ASCIIアートの要件: 隙間なく連続、行数は描画領域ちょうど、輝度で文字が変わる。"""

    CHARSET = "@%#*+=-:. "

    def setUp(self):
        self.pw, self.ph, self.lines = compute_pixel_dims(80, 24, "ascii")
        self.out = Renderer("ascii", "mono").render(
            _gradient_bytes(self.pw, self.ph), self.pw, self.ph
        )
        self.rows = self.out.split("\n")

    def test_line_count_is_exactly_the_drawing_area(self):
        self.assertEqual(len(self.rows), self.lines)
        self.assertEqual(self.lines, self.ph)

    def test_every_row_is_filled_with_characters(self):
        for row in self.rows:
            self.assertEqual(len(row), self.pw)
            self.assertTrue(row)

    def test_no_blank_gap_between_rows(self):
        # 空行を作らない（＝文字の行が連続している）
        self.assertNotIn("\n\n", self.out)
        self.assertFalse(any(row == "" for row in self.rows))

    def test_only_charset_characters_are_used(self):
        used = set("".join(self.rows))
        self.assertTrue(used <= set(self.CHARSET))
        # 10段階のうち複数段階が実際に使われている（輝度で切り替わっている）
        self.assertGreaterEqual(len(used), 5)

    def test_brightness_selects_character_in_order(self):
        row = self.rows[0]
        self.assertEqual(row[0], " ")   # 左端は黒
        self.assertEqual(row[-1], "@")  # 右端は白
        positions = [self.CHARSET.index(ch) for ch in row]
        for i in range(1, len(positions)):
            self.assertLessEqual(positions[i], positions[i - 1])


class TestRenderHalfblock(unittest.TestCase):
    def test_mono_ladder(self):
        r = Renderer("halfblock", "mono")
        pw, ph, lines = compute_pixel_dims(20, 10, "halfblock")
        # 1行目: 上=白(255), 下=黒(0) → ▀
        buf = _solid_bytes(pw, ph, 255, 255, 255)[: pw * 3] + _solid_bytes(pw, ph, 0, 0, 0)[pw * 3 : 2 * pw * 3] + _solid_bytes(pw, ph, 0, 0, 0)[2 * pw * 3 :]
        out = r.render(buf, pw, ph)
        lines_out = out.split("\n")
        self.assertEqual(len(lines_out), lines)
        self.assertTrue(all(ch == "▀" for ch in lines_out[0]))

    def test_color_uses_fg_bg(self):
        r = Renderer("halfblock", "truecolor")
        pw, ph, lines = compute_pixel_dims(20, 10, "halfblock")
        buf = _solid_bytes(pw, ph, 10, 20, 30)  # 上
        buf = buf[: pw * 3] + _solid_bytes(pw, ph, 200, 210, 220)[pw * 3 : 2 * pw * 3] + buf[2 * pw * 3 :]
        out = r.render(buf, pw, ph)
        self.assertIn("\x1b[38;2;10;20;30m", out)
        self.assertIn("\x1b[48;2;200;210;220m", out)
        self.assertIn("▀", out)


if __name__ == "__main__":
    unittest.main()