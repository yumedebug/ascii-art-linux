"""ダウンロードキャッシュ管理（~/.cache/ascii-player/）。"""

import glob
import json
import os
import time

from .utils import ensure_dir


class Cache:
    """YouTube ダウンロード動画のキャッシュ。

    ディレクトリ構成:
      ~/.cache/ascii-player/
      ├── VIDEO_ID.mp4
      └── metadata.json
    """

    def __init__(self, base_dir: str | None = None) -> None:
        if base_dir is None:
            xdg = os.environ.get("XDG_CACHE_HOME") or os.path.join(
                os.path.expanduser("~"), ".cache"
            )
            base_dir = os.path.join(xdg, "ascii-player")
        self.dir = ensure_dir(base_dir)
        self.meta_path = os.path.join(self.dir, "metadata.json")
        self.meta: dict = self._load()

    def _load(self) -> dict:
        try:
            with open(self.meta_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        tmp = self.meta_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.meta_path)

    # ---------- 参照・登録 ----------

    def get(self, key: str) -> dict | None:
        """キャッシュエントリを返す。ファイルが存在しなければ None。"""
        entry = self.meta.get(key)
        if not entry:
            return None
        path = os.path.join(self.dir, str(entry.get("file", "")))
        if not os.path.isfile(path):
            return None
        entry = dict(entry)
        entry["path"] = path
        return entry

    def put(self, key: str, entry: dict) -> None:
        entry = dict(entry)
        entry.setdefault("ts", time.time())
        self.meta[key] = entry
        self._save()

    def remove(self, key: str) -> bool:
        entry = self.meta.pop(key, None)
        if entry:
            try:
                os.remove(os.path.join(self.dir, str(entry.get("file", ""))))
            except OSError:
                pass
            self._save()
            return True
        return False

    # ---------- 一覧・容量・削除 ----------

    def list_entries(self) -> list[tuple[str, dict]]:
        """存在するファイルを持つエントリのみ返す。"""
        out = []
        for key, entry in self.meta.items():
            path = os.path.join(self.dir, str(entry.get("file", "")))
            if os.path.isfile(path):
                out.append((key, {**entry, "path": path}))
        return out

    def total_size(self) -> tuple[int, int]:
        """(ファイル数, 合計バイト数) を返す。"""
        count = 0
        total = 0
        for _, entry in self.list_entries():
            try:
                total += os.path.getsize(entry["path"])
                count += 1
            except OSError:
                pass
        return count, total

    def clear(self) -> int:
        """キャッシュを全て削除し、削除したファイル数を返す。"""
        removed = 0
        for _, entry in self.list_entries():
            try:
                os.remove(entry["path"])
                removed += 1
            except OSError:
                pass
        self.meta.clear()
        self._save()
        return removed