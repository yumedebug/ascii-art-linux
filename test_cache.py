"""cache モジュールのユニットテスト。"""

import os
import tempfile
import unittest

from ascii_player.cache import Cache


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Cache(base_dir=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_file(self, name: str, size: int = 10) -> str:
        path = os.path.join(self.cache.dir, name)
        with open(path, "wb") as f:
            f.write(b"x" * size)
        return path

    def test_cache_creation(self):
        self.assertTrue(os.path.isdir(self.cache.dir))
        self.assertEqual(self.cache.list_entries(), [])

    def test_put_and_get(self):
        self._make_file("abc123.mp4")
        self.cache.put("abc123", {"file": "abc123.mp4", "quality": "480"})
        entry = self.cache.get("abc123")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["quality"], "480")
        self.assertTrue(os.path.isfile(entry["path"]))

    def test_get_missing_key(self):
        self.assertIsNone(self.cache.get("nope"))

    def test_get_missing_file_returns_none(self):
        self.cache.put("ghost", {"file": "ghost.mp4"})  # 実ファイルなし
        self.assertIsNone(self.cache.get("ghost"))

    def test_metadata_persists(self):
        self._make_file("abc123.mp4")
        self.cache.put("abc123", {"file": "abc123.mp4"})
        cache2 = Cache(base_dir=self.tmp.name)  # 再読み込み
        self.assertIsNotNone(cache2.get("abc123"))

    def test_total_size(self):
        self._make_file("a.mp4", 100)
        self._make_file("b.mp4", 200)
        self.cache.put("a", {"file": "a.mp4"})
        self.cache.put("b", {"file": "b.mp4"})
        count, total = self.cache.total_size()
        self.assertEqual(count, 2)
        self.assertEqual(total, 300)

    def test_clear(self):
        self._make_file("a.mp4")
        self.cache.put("a", {"file": "a.mp4"})
        removed = self.cache.clear()
        self.assertEqual(removed, 1)
        self.assertEqual(self.cache.list_entries(), [])
        self.assertFalse(os.path.exists(os.path.join(self.cache.dir, "a.mp4")))

    def test_remove(self):
        self._make_file("a.mp4")
        self.cache.put("a", {"file": "a.mp4"})
        self.assertTrue(self.cache.remove("a"))
        self.assertIsNone(self.cache.get("a"))
        self.assertFalse(self.cache.remove("a"))


if __name__ == "__main__":
    unittest.main()