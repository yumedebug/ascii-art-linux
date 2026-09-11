"""cli モジュールのユニットテスト。"""

import io
import unittest
from contextlib import redirect_stdout

from ascii_player.cli import build_parser
from ascii_player.config import Config, apply_preset
from ascii_player.youtube import extract_video_id, is_youtube_url, quality_satisfies


class TestUrlDetection(unittest.TestCase):
    def test_watch_url(self):
        self.assertTrue(is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_youtu_be(self):
        self.assertTrue(is_youtube_url("https://youtu.be/dQw4w9WgXcQ"))

    def test_shorts(self):
        self.assertTrue(is_youtube_url("https://www.youtube.com/shorts/dQw4w9WgXcQ"))

    def test_music_youtube(self):
        self.assertTrue(is_youtube_url("https://music.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_local_path_is_not_url(self):
        self.assertFalse(is_youtube_url("video.mp4"))
        self.assertFalse(is_youtube_url("/home/user/Videos/movie.mp4"))
        self.assertFalse(is_youtube_url("https://example.com/foo.mp4"))

    def test_extract_id(self):
        self.assertEqual(extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_video_id("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertIsNone(extract_video_id("video.mp4"))


class TestQuality(unittest.TestCase):
    def test_satisfies(self):
        self.assertTrue(quality_satisfies("720", "360"))
        self.assertTrue(quality_satisfies("720", "720"))
        self.assertTrue(quality_satisfies("best", "1080"))
        self.assertFalse(quality_satisfies("360", "720"))
        self.assertFalse(quality_satisfies(None, "480"))
        self.assertFalse(quality_satisfies("480", "best"))


class TestParser(unittest.TestCase):
    def test_local_file(self):
        args = build_parser().parse_args(["video.mp4"])
        self.assertEqual(args.input, "video.mp4")

    def test_options(self):
        args = build_parser().parse_args(
            ["URL", "--mode", "blocks", "--quality", "1080", "--no-audio", "--no-hud", "--loop"]
        )
        self.assertEqual(args.mode, "blocks")
        self.assertEqual(args.quality, "1080")
        self.assertTrue(args.no_audio)
        self.assertTrue(args.no_hud)
        self.assertTrue(args.loop)

    def test_invalid_mode_rejected(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["x", "--mode", "bogus"])

    def test_invalid_quality_rejected(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["x", "--quality", "9999"])

    def test_width_height(self):
        args = build_parser().parse_args(["x", "--width", "100", "--height", "30"])
        self.assertEqual(args.width, 100)
        self.assertEqual(args.height, 30)

    def test_version(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit), redirect_stdout(buf):
            build_parser().parse_args(["--version"])
        self.assertIn("ascii-player", buf.getvalue())


class TestPreset(unittest.TestCase):
    def test_low_preset(self):
        cfg = Config(input="x")
        apply_preset(cfg)
        self.assertEqual(cfg.preset, "normal")
        cfg.preset = "low"
        apply_preset(cfg)
        self.assertEqual(cfg.mode, "ascii")
        self.assertEqual(cfg.max_fps, 30.0)
        self.assertIsNotNone(cfg.max_cols)

    def test_quality_preset(self):
        cfg = Config(input="x")
        cfg.preset = "quality"
        apply_preset(cfg)
        self.assertEqual(cfg.mode, "halfblock")

    def test_explicit_mode_overrides_preset(self):
        cfg = Config(input="x")
        cfg.preset = "low"
        apply_preset(cfg)
        cfg.mode = "halfblock"  # CLIの明示指定に相当
        self.assertEqual(cfg.mode, "halfblock")


if __name__ == "__main__":
    unittest.main()