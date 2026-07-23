"""yt-dlp 音乐源：统一封装 YouTube 与 Bilibili 的搜索和取流。

性能策略：
- B站搜索优先走官方 API（~1s，见 bilibili_api.py），失败才回落到 yt-dlp
  逐条解析（~30s，慢但稳）；
- 搜索结果进程内缓存 10 分钟；
- yt-dlp 延迟导入，不拖慢启动。

实测坑位（yt-dlp 兜底路径）：
- B站搜索接口没有浏览器 UA 会返回 HTTP 412；
- B站搜索结果可能混入付费课程 (cheese) 页面，无 ignoreerrors 会中断整批；
- B站 flat 搜索只有 id 没有标题，必须完整解析；
- B站 CDN 音频流没有 Referer 会 403，请求头必须传给播放器。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from yueting.models import Source, Track
from yueting.sources.bilibili_api import BilibiliApi, BilibiliApiError

YoutubeDL = None  # 延迟导入占位；测试通过 patch 替换


def _ydl_class():
    global YoutubeDL
    if YoutubeDL is None:
        from yt_dlp import YoutubeDL as _YoutubeDL

        YoutubeDL = _YoutubeDL
    return YoutubeDL


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

_SEARCH_CACHE_TTL_SECONDS = 600.0


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

    def __init__(
        self,
        bili_api: BilibiliApi | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._bili_api = bili_api if bili_api is not None else BilibiliApi()
        self._clock = clock
        self._search_cache: dict[tuple[str, str, int], tuple[list[Track], float]] = {}
        self._parts_cache: dict[str, list[Track]] = {}

    def search(self, query: str, source: Source, limit: int = 10) -> list[Track]:
        query = query.strip()
        if not query:
            raise ValueError("搜索词不能为空")

        cache_key = (query, source.value, limit)
        cached = self._search_cache.get(cache_key)
        if cached is not None and self._clock() - cached[1] < _SEARCH_CACHE_TTL_SECONDS:
            return list(cached[0])

        if source is Source.BILIBILI:
            try:
                results = self._bili_api.search(query, limit=limit)
            except BilibiliApiError:
                results = self._search_via_ytdlp(query, source, limit)
        else:
            results = self._search_via_ytdlp(query, source, limit)

        self._search_cache[cache_key] = (list(results), self._clock())
        return results

    def _search_via_ytdlp(self, query: str, source: Source, limit: int) -> list[Track]:
        expr = f"{_SEARCH_PREFIX[source]}{limit}:{query}"
        try:
            with _ydl_class()(_SEARCH_OPTS[source]) as ydl:
                info = ydl.extract_info(expr, download=False)
        except Exception as exc:
            raise SearchError(f"搜索失败（{source.display}）：{exc}") from exc
        entries = (info or {}).get("entries") or []
        tracks = (_entry_to_track(e, source) for e in entries)
        return [t for t in tracks if t is not None]

    def expand_parts(self, track: Track) -> list[Track]:
        """B站多分P视频展开为每P一首；单P/非B站/已是分P则原样返回。

        50P 音乐合集由此变成现成的 50 首播放队列。查询失败时静默退回
        原曲目（届时播放 P1，与旧行为一致）。
        """
        if track.source is not Source.BILIBILI or "?p=" in track.webpage_url:
            return [track]
        cached = self._parts_cache.get(track.id)
        if cached is not None:
            return list(cached)
        try:
            pages = self._bili_api.pages(track.id)
        except BilibiliApiError:
            return [track]
        if len(pages) <= 1:
            result = [track]
        else:
            result = [
                Track(
                    id=f"{track.id}-p{page.page}",
                    source=Source.BILIBILI,
                    title=page.title.strip() or f"{track.title} P{page.page}",
                    uploader=track.uploader,
                    duration=page.duration,
                    webpage_url=f"https://www.bilibili.com/video/{track.id}?p={page.page}",
                )
                for page in pages
            ]
        self._parts_cache[track.id] = list(result)
        return result

    def resolve_stream_url(self, webpage_url: str) -> StreamInfo:
        try:
            with _ydl_class()(_STREAM_OPTS) as ydl:
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
