"""audio モジュール（音声再生）のユニットテスト。"""

import subprocess
import unittest

from ascii_player.audio import AudioPlayer, atempo_args, sink_command


class _FakeProcess:
    def __init__(self, returncode=None):
        self._rc = returncode

    def poll(self):
        return self._rc


class TestSinkCommand(unittest.TestCase):
    def test_aplay_uses_alsa_format_name(self):
        # aplay の -f は ALSA 名（S16_LE）でなければならない。
        # ffmpeg 形式の "s16le" を渡すと aplay は
        # 「不正な拡張フォーマット」で即終了し、無音になる。
        cmd = sink_command("aplay", rate=48000, channels=2)
        self.assertEqual(cmd[0], "aplay")
        self.assertIn("S16_LE", cmd)
        self.assertNotIn("s16le", cmd)
        self.assertIn("48000", cmd)
        self.assertIn("2", cmd)

    def test_ffplay_uses_ffmpeg_format_name(self):
        cmd = sink_command("ffplay", rate=44100, channels=1)
        self.assertEqual(cmd[0], "ffplay")
        self.assertIn("s16le", cmd)
        self.assertIn("44100", cmd)
        self.assertIn("pipe:0", cmd)

    def test_commands_are_absolute_tool_names(self):
        # find_tool で見つけた実行ファイル名をそのまま使う
        for name in ("aplay", "ffplay"):
            self.assertTrue(sink_command(name))


class TestAtempo(unittest.TestCase):
    def test_normal_speed_is_noop(self):
        self.assertEqual(atempo_args(1.0), [])

    def test_fast_speed_is_split(self):
        # atempo は 2.0 までしか受け付けないので分割する
        args = atempo_args(4.0)
        self.assertGreaterEqual(len(args), 2)
        self.assertTrue(all(a.startswith("atempo=") for a in args))

    def test_slow_speed_is_split(self):
        args = atempo_args(0.25)
        self.assertGreaterEqual(len(args), 2)


class TestFailureDetection(unittest.TestCase):
    def test_no_sink_is_not_failure(self):
        ap = AudioPlayer("x.mp4")
        ap.sink = None
        self.assertFalse(ap.failed())

    def test_running_sink_is_not_failure(self):
        ap = AudioPlayer("x.mp4")
        ap.sink = _FakeProcess(None)
        self.assertFalse(ap.failed())
        self.assertTrue(ap.is_alive())

    def test_error_exit_is_failure(self):
        ap = AudioPlayer("x.mp4")
        ap.sink = _FakeProcess(1)
        self.assertTrue(ap.failed())

    def test_normal_exit_is_not_failure(self):
        ap = AudioPlayer("x.mp4")
        ap.sink = _FakeProcess(0)
        self.assertFalse(ap.failed())


if __name__ == "__main__":
    unittest.main()
