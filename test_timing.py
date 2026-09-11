"""timing モジュールのユニットテスト。"""

import time
import unittest

from ascii_player.timing import FrameScheduler, MediaClock


class TestMediaClock(unittest.TestCase):
    def test_advances_with_wall_time(self):
        clock = MediaClock()
        t0 = clock.now()
        time.sleep(0.05)
        t1 = clock.now()
        self.assertGreaterEqual(t1 - t0, 0.04)
        self.assertLess(t1 - t0, 0.5)

    def test_seek_sets_position(self):
        clock = MediaClock()
        clock.seek(12.5)
        self.assertAlmostEqual(clock.now(), 12.5, delta=0.5)

    def test_pause_freezes_clock(self):
        clock = MediaClock()
        time.sleep(0.03)
        clock.pause()
        pos = clock.now()
        time.sleep(0.05)
        self.assertAlmostEqual(clock.now(), pos, delta=0.01)

    def test_pause_resume_accumulates(self):
        clock = MediaClock()
        clock.pause()
        time.sleep(0.05)
        clock.resume()
        pos = clock.now()
        time.sleep(0.05)
        self.assertGreaterEqual(clock.now() - pos, 0.04)

    def test_rate_speeds_up_clock(self):
        clock = MediaClock(rate=2.0)
        time.sleep(0.05)
        pos = clock.now()
        self.assertGreater(pos, 0.05)  # 実時間の約2倍進む

    def test_seek_while_paused(self):
        clock = MediaClock()
        clock.pause()
        clock.seek(30.0)
        self.assertAlmostEqual(clock.now(), 30.0, delta=0.01)
        clock.resume()
        self.assertGreaterEqual(clock.now(), 30.0)


class TestFrameScheduler(unittest.TestCase):
    def test_frame_duration(self):
        sched = FrameScheduler(30.0)
        self.assertAlmostEqual(sched.frame_dur, 1 / 30)

    def test_frame_time(self):
        sched = FrameScheduler(30.0)
        self.assertAlmostEqual(sched.frame_time(0, 10.0), 10.0)
        self.assertAlmostEqual(sched.frame_time(30, 10.0), 11.0)

    def test_should_drop(self):
        sched = FrameScheduler(30.0)
        # 表示時刻より1フレーム以上過ぎている → ドロップ
        self.assertTrue(sched.should_drop(10.0, 10.0 + sched.frame_dur + 0.001))
        # まだ時刻前 → ドロップしない
        self.assertFalse(sched.should_drop(10.0, 9.5))
        # ちょうど1フレーム遅れは許容
        self.assertFalse(sched.should_drop(10.0, 10.0 + sched.frame_dur))

    def test_wait_time(self):
        sched = FrameScheduler(30.0)
        self.assertAlmostEqual(sched.wait_time(10.0, 9.5), 0.5)
        self.assertEqual(sched.wait_time(10.0, 10.5), 0.0)


if __name__ == "__main__":
    unittest.main()