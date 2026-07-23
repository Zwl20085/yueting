"""yt-dlp 音乐源：统一封装 YouTube 与 Bilibili 的搜索和取流。"""
from __future__ import annotations

from yt_dlp import YoutubeDL

from yueting.models import Source, Track

_SEARCH_PREFIX = {
    Source.YOUTUBE: "ytsearch",
    Source.BILIBILI: "bilisearch",
}

_SEARCH_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",  # 搜索只取元数据，不解析每个视频
    "skip_download": True,
}

_STREAM_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "format": "bestaudio/best",
    "skip_download": True,
    "noplaylist": True,
}


class SearchError(Exception):
    pass


def _entry_to_track(entry: dict | None, source: Source) -> Track | None:
    if not entry or not entry.get("id"):
        return None
    return Track(
        id=str(entry["id"]),
        source=source,
        title=entry.get("title") or "(无标题)",
        uploader=entry.get("uploader") or "",
        duration=entry.get("duration"),
        webpage_url=entry.get("webpage_url") or entry.get("url") or "",
    )


class YtdlpSource:
    """MusicSource 实现：搜索返回 Track 列表，播放前解析音频流 URL。"""

    def search(self, query: str, source: Source, limit: int = 10) -> list[Track]:
        query = query.strip()
        if not query:
            raise ValueError("搜索词不能为空")
        expr = f"{_SEARCH_PREFIX[source]}{limit}:{query}"
        try:
            with YoutubeDL(_SEARCH_OPTS) as ydl:
                info = ydl.extract_info(expr, download=False)
        except Exception as exc:
            raise SearchError(f"搜索失败（{source.display}）：{exc}") from exc
        entries = (info or {}).get("entries") or []
        tracks = (_entry_to_track(e, source) for e in entries)
        return [t for t in tracks if t is not None]

    def resolve_stream_url(self, webpage_url: str) -> str:
        try:
            with YoutubeDL(_STREAM_OPTS) as ydl:
                info = ydl.extract_info(webpage_url, download=False)
        except Exception as exc:
            raise SearchError(f"取流失败：{exc}") from exc
        url = (info or {}).get("url")
        if not url:
            formats = (info or {}).get("formats") or []
            audio = [f for f in formats if f.get("acodec") not in (None, "none") and f.get("url")]
            if audio:
                url = audio[-1]["url"]
        if not url:
            raise SearchError("取流失败：未找到可用音频流")
        return url
