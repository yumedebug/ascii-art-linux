"""YouTube動画のダウンロードとキャッシュの統合。

- URL 入力: yt-dlp でキャッシュへダウンロード（既にあれば再利用）
- ローカルファイル: そのまま再生
ユーザー入力をシェル文字列へ連結せず、yt-dlp のPython APIのみを使う。
"""

import glob
import os
import time

from . import youtube
from .utils import AppError, human_size


def resolve_input(input_str: str, cfg, cache) -> str:
    """入力を解決してローカルファイルパスを返す。"""
    if youtube.is_youtube_url(input_str):
        return download_youtube(input_str, cfg.quality, cache, cfg.debug)
    path = os.path.abspath(os.path.expanduser(input_str))
    if not os.path.isfile(path):
        raise AppError(f"ファイルが見つかりません: {input_str}")
    return path


def download_youtube(url: str, quality: str = "480", cache=None, debug: bool = False) -> str:
    """YouTube動画をダウンロード（キャッシュヒット時は再利用）してパスを返す。"""
    vid = youtube.extract_video_id(url)
    if not vid:
        raise AppError("YouTubeのURLを認識できませんでした。")

    if cache is not None:
        entry = cache.get(vid)
        if entry and youtube.quality_satisfies(entry.get("quality"), quality):
            if debug:
                print(f"キャッシュヒット: {entry['path']}", file=__import__("sys").stderr)
            return entry["path"]

    info = youtube.get_info(url, debug=debug)
    actual_id = info.get("id") or vid

    cache_dir = cache.dir if cache is not None else os.path.join(
        os.path.expanduser("~"), ".cache", "ascii-player"
    )
    opts = {
        "format": youtube.QUALITY_FORMATS.get(quality, youtube.QUALITY_FORMATS["best"]),
        "outtmpl": os.path.join(cache_dir, f"{actual_id}.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": not debug,
        "no_warnings": True,
        "progress_hooks": [_progress_hook],
    }
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        raise AppError("yt-dlp がインストールされていません。", hint="pip install yt-dlp")
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:
        raise AppError(youtube._friendly_yt_error(e), hint=str(e)) from e

    matches = [
        m
        for m in sorted(
            glob.glob(os.path.join(cache_dir, f"{actual_id}.*")), key=os.path.getmtime
        )
        if not m.endswith(".part")
    ]
    if not matches:
        raise AppError("ダウンロードに失敗しました。キャッシュとディスク容量を確認してください。")
    path = matches[-1]

    if cache is not None:
        cache.put(
            actual_id,
            {
                "url": url,
                "title": info.get("title", ""),
                "file": os.path.basename(path),
                "quality": quality,
                "ts": time.time(),
            },
        )
    return path


def _progress_hook(d: dict) -> None:
    """yt-dlp のダウンロード進捗を1行で表示する。"""
    status = d.get("status")
    if status == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        done = d.get("downloaded_bytes") or 0
        pct = 100.0 * done / total if total else 0.0
        print(f"\rダウンロード中... {pct:5.1f}% ({human_size(done)}/{human_size(total)})", end="", flush=True)
    elif status == "finished":
        print("\rダウンロード完了。                    ", flush=True)