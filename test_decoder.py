"""decoder モジュールのユニットテスト（FFmpeg不要のバッファ動作）。"""

import os
import unittest

from ascii_player.decoder import VideoDecoder, parse_fps


def make_decoder(frames: list[bytes], frame_size: int = 4):
    """ffmpeg を起動せず、バッファとパイプだけを持つデコーダを作る。

    書き込み側を閉じたパイプを渡すので、パイプは即EOF状態になる。
    """
    fd_r, fd_w = os.pipe()
    os.close(fd_w)
    os.set_blocking(fd_r, False)
    decoder = VideoDecoder.__new__(VideoDecoder)
    decoder.frame_size = frame_size
    decoder._buf = bytearray(b"".join(frames))
    decoder._eof = False
    decoder._fd = fd_r
    return decoder, fd_r


class TestReadFrameBuffer(unittest.TestCase):
    """バッファに溜まったフレームを EOF で捨てないこと（再生が途中で止まる不具合）。"""

    def test_buffered_frames_are_returned_before_eof(self):
        decoder, fd = make_decoder([b"aaaa", b"bbbb", b"cccc"])
        try:
            self.assertEqual(decoder.read_frame(), b"aaaa")
            self.assertEqual(decoder.read_frame(), b"bbbb")
            self.assertEqual(decoder.read_frame(), b"cccc")
            # バッファを使い切ってから EOF
            self.assertEqual(decoder.read_frame(), b"")
        finally:
            os.close(fd)

    def test_eof_is_not_reported_while_frames_remain(self):
        decoder, fd = make_decoder([b"aaaa", b"bb"])  # 1フレーム + 端数
        try:
            self.assertEqual(decoder.read_frame(), b"aaaa")
            self.assertEqual(decoder.read_frame(), b"")
        finally:
            os.close(fd)

    def test_partial_frame_is_discarded_at_eof(self):
        decoder, fd = make_decoder([b"ab"])
        try:
            # 端数（不完全なフレーム）は返さず EOF にする。壊れた絵を出さない
            self.assertEqual(decoder.read_frame(), b"")
        finally:
            os.close(fd)

    def test_eof_is_sticky(self):
        decoder, fd = make_decoder([])
        try:
            self.assertEqual(decoder.read_frame(), b"")
            self.assertEqual(decoder.read_frame(), b"")
        finally:
            os.close(fd)


class TestParseFps(unittest.TestCase):
    def test_fraction(self):
        self.assertAlmostEqual(parse_fps("30000/1001"), 29.97, places=2)

    def test_plain(self):
        self.assertEqual(parse_fps("25"), 25.0)

    def test_invalid(self):
        self.assertIsNone(parse_fps(None))
        self.assertIsNone(parse_fps("abc"))
        self.assertIsNone(parse_fps("1/0"))


if __name__ == "__main__":
    unittest.main()
