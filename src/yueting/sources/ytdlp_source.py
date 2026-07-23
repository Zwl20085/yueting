"""yt-dlp 音乐源：统一封装 YouTube 与 Bilibili 的搜索和取流。

实测坑位：
- B站搜索接口没有浏览器 UA 会返回 HTTP 412；
- B站搜索结果可能混入付费课程 (cheese) 页面，无 ignoreerrors 会中断整批；
- B站 flat 搜索只有 id 没有标题，必须完整解析（慢一些但可用）；
- B站 CDN 音频流没有 Referer 会 403，请求头必须传给播放器。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from yt_dlp import YoutubeDL

from yueting.models import Source, Track

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_SEARCH_PREFIX = {
    Source.YOUTUBE: "ytsearch",
    Source.BILIBILI: "bilisearch",
}

_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
}

_SEARCH_OPTS = {
    Source.YOUTUBE: {
        **_BASE_OPTS,
        "extract_flat": "in_playlist",  # 油管 flat 搜索自带标题，快
    },
    Source.BILIBILI: {
        **_BASE_OPTS,
        "noplaylist": True,
        "ignoreerrors": True,
        "http_headers": {"User-Agent": _BROWSER_UA, "Referer": "https://www.bilibili.com/"},
    },
}

_STREAM_OPTS = {
    **_BASE_OPTS,
    "format": "bestaudio/best",
    "noplaylist": True,
    "http_headers": {"User-Agent": _BROWSER_UA},
}


class SearchError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class StreamInfo:
    """可播放的音频流：URL + 播放器请求时必须携带的 HTTP 头。"""

    url: str
    headers: dict[str, str] = field(default_factory=dict)


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
    """MusicSource 实现：搜索返回 Track 列表，播放前解析音频流。"""

    def search(self, query: str, source: Source, limit: int = 10) -> list[Track]:
        query = query.strip()
        if not query:
            raise ValueError("搜索词不能为空")
        expr = f"{_SEARCH_PREFIX[source]}{limit}:{query}"
        try:
            with YoutubeDL(_SEARCH_OPTS[source]) as ydl:
                info = ydl.extract_info(expr, download=False)
        except Exception as exc:
            raise SearchError(f"搜索失败（{source.display}）：{exc}") from exc
        entries = (info or {}).get("entries") or []
        tracks = (_entry_to_track(e, source) for e in entries)
        return [t for t in tracks if t is not None]

    def resolve_stream_url(self, webpage_url: str) -> StreamInfo:
        try:
            with YoutubeDL(_STREAM_OPTS) as ydl:
                info = ydl.extract_info(webpage_url, download=False)
        except Exception as exc:
            raise SearchError(f"取流失败：{exc}") from exc
        info = info or {}
        url = info.get("url")
        headers = info.get("http_headers") or {}
        if not url:
            formats = info.get("formats") or []
            audio = [f for f in formats if f.get("acodec") not in (None, "none") and f.get("url")]
            if audio:
                best = audio[-1]
                url = best["url"]
                headers = best.get("http_headers") or headers
        if not url:
            raise SearchError("取流失败：未找到可用音频流")
        return StreamInfo(url=url, headers=dict(headers))
