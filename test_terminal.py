"""terminal モジュール（端末制御）のユニットテスト。"""

import struct
import unittest
from unittest import mock

from ascii_player import terminal as term


class TestCellRatio(unittest.TestCase):
    def test_nominal(self):
        # 80列24行、1セルが 8x16px → 高さ/幅 = 2.0
        self.assertAlmostEqual(term.cell_ratio_from_size(24, 80, 80 * 8, 24 * 16), 2.0)

    def test_unknown_pixel_size_returns_none(self):
        # 端末がピクセルサイズを返さない場合は判定しない
        self.assertIsNone(term.cell_ratio_from_size(24, 80, 0, 0))
        self.assertIsNone(term.cell_ratio_from_size(0, 0, 640, 480))

    def test_absurd_value_rejected(self):
        # 誤検出（ありえない比率）は採用しない
        self.assertIsNone(term.cell_ratio_from_size(24, 80, 1000, 1))
        self.assertIsNone(term.cell_ratio_from_size(1, 1, 1 << 14, 1))

    def test_narrow_cell_ratio_is_detected(self):
        # 1セルが 10x14px（高さ/幅 = 1.4）のような端末も正しく扱う
        self.assertAlmostEqual(term.cell_ratio_from_size(24, 80, 80 * 10, 24 * 14), 1.4)

    def test_fallback_when_ioctl_fails(self):
        with mock.patch.object(term.fcntl, "ioctl", side_effect=OSError("not a tty")):
            self.assertEqual(term.detect_cell_ratio(1.75), 1.75)
            self.assertEqual(term.detect_cell_ratio(), term.DEFAULT_CELL_RATIO)

    def test_fallback_when_pixel_size_is_zero(self):
        buf = struct.pack("HHHH", 24, 80, 0, 0)
        with mock.patch.object(term.fcntl, "ioctl", return_value=buf):
            self.assertEqual(term.detect_cell_ratio(), term.DEFAULT_CELL_RATIO)

    def test_detects_from_ioctl(self):
        # TIOCGWINSZ の並びは rows, cols, xpixel, ypixel
        buf = struct.pack("HHHH", 24, 80, 80 * 8, 24 * 16)
        with mock.patch.object(term.fcntl, "ioctl", return_value=buf):
            self.assertAlmostEqual(term.detect_cell_ratio(), 2.0)


if __name__ == "__main__":
    unittest.main()
