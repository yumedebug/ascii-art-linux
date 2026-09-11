"""YouTube URL判定・ID抽出・動画情報取得・画質選択。"""

import re

from .utils import AppError

_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.|music\.)?"
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/|v/)|youtu\.be/)"
    r"([a-zA-Z0-9_-]{11})",
    re.IGNORECASE,
)

# 画質 → yt-dlp フォーマット指定。
# 「画質以下の動画+音声、なければ動画のみ、なければ任意」の順で選択し、
# 必要に応じて FFmpeg で音声と結合する（yt-dlp が自動で行う）。
QUALITY_FORMATS = {
    "360": "bv*[height<=360]+ba/b[height<=360]/bv*+ba/b",
    "480": "bv*[height<=480]+ba/b[height<=480]/bv*+ba/b",
    "720": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
    "best": "bv*+ba/b",
}

QUALITY_RANK = {"360": 360, "480": 480, "720": 720, "1080": 1080, "best": 9999}


def is_youtube_url(text: str) -> bool:
    """入力が YouTube のURLかどうか。"""
    return bool(_URL_RE.search(text))


def extract_video_id(url: str) -> str | None:
    """YouTube URL から 11桁の動画IDを抽出する。"""
    m = _URL_RE.search(url)
    return m.group(1) if m else None


def quality_satisfies(cached_quality: str | None, requested: str) -> bool:
    """キャッシュ済み画質が要求画質を満たすか。"""
    if not cached_quality:
        return False
    return QUALITY_RANK.get(cached_quality, 0) >= QUALITY_RANK.get(requested, 0)


def _friendly_yt_error(exc: Exception) -> str:
    """yt-dlp の例外をユーザー向けメッセージへ変換する。"""
    msg = str(exc).lower()
    if "private" in msg:
        return "この動画は非公開です。"
    if "removed" in msg or "deleted" in msg or "unavailable" in msg or "not found" in msg:
        return "この動画は削除されているか利用できません。"
    if "age" in msg or "18" in msg or "age-restricted" in msg:
        return "年齢制限により取得できない可能性があります。"
    if "sign in" in msg or "login" in msg:
        return "ログインが必要な動画です。"
    if "unable to download" in msg or "network" in msg or "timeout" in msg:
        return "ネットワークエラーが発生しました。接続を確認してください。"
    return "YouTube動画の取得に失敗しました。"


def get_info(url: str, debug: bool = False) -> dict:
    """yt-dlp で動画情報を取得する（ダウンロードはしない）。"""
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        raise AppError("yt-dlp がインストールされていません。", hint="pip install yt-dlp")
    opts = {"quiet": not debug, "no_warnings": True, "noplaylist": True}
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise AppError(_friendly_yt_error(e), hint=str(e)) from e
    if not info:
        raise AppError("動画情報を取得できませんでした。")
    return info