"""B站官方搜索 API 客户端：一次请求返回全部结果（~1s），替代逐条视频解析（~35s）。

流程：先访问 bilibili.com 首页拿 buvid3 cookie（无 cookie 搜索接口返回 412），
再调 /x/web-interface/search/type。cookie 进程内缓存，失效自动重取一次。
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from yueting.models import Source, Track

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_HOMEPAGE = "https://www.bilibili.com/"
_SEARCH_URL = (
    "https://api.bilibili.com/x/web-interface/search/type"
    "?search_type=video&keyword={keyword}"
)
_PAGELIST_URL = "https://api.bilibili.com/x/player/pagelist?bvid={bvid}"
_EM_TAG = re.compile(r"</?em[^>]*>")
_TIMEOUT_SECONDS = 10

# fetcher(url, headers) -> (body_bytes, response_headers_dict)
Fetcher = Callable[[str, dict], tuple[bytes, dict]]


class BilibiliApiError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class VideoPage:
    """视频的一个分P。"""

    page: int
    title: str
    duration: float | None


def _default_fetcher(url: str, headers: dict) -> tuple[bytes, dict]:  # pragma: no cover
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as resp:
        set_cookies = resp.headers.get_all("Set-Cookie") or []
        cookie = "; ".join(c.split(";")[0] for c in set_cookies)
        return resp.read(), ({"Set-Cookie": cookie} if cookie else {})


def _clean_title(raw: str) -> str:
    return html.unescape(_EM_TAG.sub("", raw))


def _parse_duration(raw: str) -> float | None:
    parts = raw.split(":") if raw else []
    if not parts or not all(p.isdigit() for p in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return float(seconds)


def _result_to_track(item: dict) -> Track | None:
    bvid = item.get("bvid") or ""
    title = _clean_title(item.get("title") or "")
    if not bvid or not title.strip():
        return None
    return Track(
        id=bvid,
        source=Source.BILIBILI,
        title=title,
        uploader=item.get("author") or "",
        duration=_parse_duration(item.get("duration") or ""),
        webpage_url=f"https://www.bilibili.com/video/{bvid}",
    )


class BilibiliApi:
    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self._fetch = fetcher or _default_fetcher
        self._cookie: str | None = None

    def _ensure_cookie(self) -> str:
        if self._cookie is None:
            _, headers = self._fetch(_HOMEPAGE, {"User-Agent": _UA})
            self._cookie = headers.get("Set-Cookie", "")
        return self._cookie

    def search(self, query: str, limit: int = 20) -> list[Track]:
        query = query.strip()
        if not query:
            raise ValueError("搜索词不能为空")
        try:
            cookie = self._ensure_cookie()
            url = _SEARCH_URL.format(keyword=urllib.parse.quote(query))
            body, _ = self._fetch(
                url,
                {"User-Agent": _UA, "Referer": _HOMEPAGE, "Cookie": cookie},
            )
            data = json.loads(body)
        except (OSError, ValueError) as exc:
            self._cookie = None  # 失败后下次重新取 cookie
            raise BilibiliApiError(f"B站搜索接口异常：{exc}") from exc
        if data.get("code") != 0:
            self._cookie = None
            raise BilibiliApiError(f"B站搜索接口异常：{data.get('message', data.get('code'))}")
        items = (data.get("data") or {}).get("result") or []
        tracks = (_result_to_track(item) for item in items)
        return [t for t in tracks if t is not None][:limit]

    def pages(self, bvid: str) -> tuple[VideoPage, ...]:
        """查询视频的分P列表（合集视频=现成的歌单）。"""
        try:
            body, _ = self._fetch(
                _PAGELIST_URL.format(bvid=bvid),
                {"User-Agent": _UA, "Referer": _HOMEPAGE},
            )
            data = json.loads(body)
        except (OSError, ValueError) as exc:
            raise BilibiliApiError(f"分P列表获取失败：{exc}") from exc
        if data.get("code") != 0:
            raise BilibiliApiError(f"分P列表获取失败：{data.get('message', data.get('code'))}")
        return tuple(
            VideoPage(
                page=int(item.get("page") or 0),
                title=str(item.get("part") or ""),
                duration=float(item["duration"]) if item.get("duration") is not None else None,
            )
            for item in (data.get("data") or [])
        )
