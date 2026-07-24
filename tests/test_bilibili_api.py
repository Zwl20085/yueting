"""Tests for the fast Bilibili search API client (fetcher injected, no network)."""
import json

import pytest

from yueting.models import Source
from yueting.sources.bilibili_api import (
    BilibiliApi,
    BilibiliApiError,
    VideoPage,
    _parse_duration,
    _clean_title,
    _result_to_track,
)


def api_item(**overrides):
    base = {
        "bvid": "BV1BZbSzZEGT",
        "title": '【Hi-Res】《<em class="keyword">晴天</em>》- 周杰伦',
        "author": "VV音乐局",
        "duration": "4:30",
        "arcurl": "http://www.bilibili.com/video/av114981911727491",
    }
    base.update(overrides)
    return base


def api_response(items):
    return json.dumps(
        {"code": 0, "message": "0", "data": {"result": items}}
    ).encode("utf-8")


class FakeFetcher:
    """Records requests; returns canned bodies per URL prefix."""

    def __init__(self, search_body: bytes, cookie: str = "buvid3=abc"):
        self.search_body = search_body
        self.cookie = cookie
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict) -> tuple[bytes, dict]:
        self.calls.append(url)
        if "api.bilibili.com" in url:
            assert "Cookie" in headers, "搜索请求必须带 cookie"
            return self.search_body, {}
        return b"<html>", {"Set-Cookie": f"{self.cookie}; Path=/"}


class TestParsing:
    def test_parse_duration_mm_ss(self):
        assert _parse_duration("4:30") == 270.0

    def test_parse_duration_h_mm_ss(self):
        assert _parse_duration("1:02:05") == 3725.0

    def test_parse_duration_garbage_returns_none(self):
        assert _parse_duration("") is None
        assert _parse_duration("abc") is None

    def test_clean_title_strips_em_and_entities(self):
        raw = '循环《<em class="keyword">晴天</em>》|&quot;刮风&quot;'
        assert _clean_title(raw) == '循环《晴天》|"刮风"'

    def test_result_to_track(self):
        track = _result_to_track(api_item())
        assert track.id == "BV1BZbSzZEGT"
        assert track.source == Source.BILIBILI
        assert "晴天" in track.title and "<em" not in track.title
        assert track.uploader == "VV音乐局"
        assert track.duration == 270.0
        assert track.webpage_url == "https://www.bilibili.com/video/BV1BZbSzZEGT"

    def test_result_without_bvid_skipped(self):
        assert _result_to_track(api_item(bvid="")) is None


class TestSearch:
    def test_search_returns_tracks(self):
        fetcher = FakeFetcher(api_response([api_item(), api_item(bvid="BV2")]))
        api = BilibiliApi(fetcher=fetcher)
        tracks = api.search("晴天", limit=10)
        assert len(tracks) == 2
        assert all(t.source == Source.BILIBILI for t in tracks)

    def test_search_respects_limit(self):
        items = [api_item(bvid=f"BV{i}") for i in range(20)]
        api = BilibiliApi(fetcher=FakeFetcher(api_response(items)))
        assert len(api.search("晴天", limit=5)) == 5

    def test_cookie_fetched_once_and_reused(self):
        fetcher = FakeFetcher(api_response([api_item()]))
        api = BilibiliApi(fetcher=fetcher)
        api.search("晴天")
        api.search("稻香")
        homepage_calls = [c for c in fetcher.calls if "api.bilibili.com" not in c]
        assert len(homepage_calls) == 1

    def test_api_error_code_raises(self):
        body = json.dumps({"code": -412, "message": "请求被拦截"}).encode()
        api = BilibiliApi(fetcher=FakeFetcher(body))
        with pytest.raises(BilibiliApiError, match="请求被拦截"):
            api.search("晴天")

    def test_network_failure_raises_api_error(self):
        def bad_fetcher(url, headers):
            raise OSError("connection reset")

        api = BilibiliApi(fetcher=bad_fetcher)
        with pytest.raises(BilibiliApiError):
            api.search("晴天")

    def test_blank_query_raises_value_error(self):
        api = BilibiliApi(fetcher=FakeFetcher(api_response([])))
        with pytest.raises(ValueError):
            api.search("  ")


def pagelist_response(parts):
    return json.dumps({"code": 0, "data": parts}).encode("utf-8")


def playurl_response(audios):
    return json.dumps({"code": 0, "data": {"dash": {"audio": audios}}}).encode("utf-8")


class PagelistFetcher:
    def __init__(self, body: bytes):
        self.body = body
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict) -> tuple[bytes, dict]:
        self.calls.append(url)
        return self.body, {}


class RoutingFetcher:
    """Routes pagelist vs playurl URLs to different canned bodies."""

    def __init__(self, pagelist_body: bytes, playurl_body: bytes):
        self.bodies = {"pagelist": pagelist_body, "playurl": playurl_body}
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict) -> tuple[bytes, dict]:
        self.calls.append(url)
        for marker, body in self.bodies.items():
            if marker in url:
                return body, {}
        return b"<html>", {"Set-Cookie": "buvid3=x"}


TWO_PARTS = [
    {"page": 1, "part": "001.周杰伦-晴天", "duration": 270, "cid": 111},
    {"page": 2, "part": "002.周杰伦-夜曲", "duration": 227, "cid": 222},
]


class TestPages:
    def test_pages_returns_video_pages(self):
        api = BilibiliApi(fetcher=PagelistFetcher(pagelist_response(TWO_PARTS)))
        pages = api.pages("BV1FPjy6TEiE")
        assert pages == (
            VideoPage(page=1, title="001.周杰伦-晴天", duration=270.0, cid=111),
            VideoPage(page=2, title="002.周杰伦-夜曲", duration=227.0, cid=222),
        )

    def test_pages_requests_correct_bvid(self):
        fetcher = PagelistFetcher(pagelist_response([]))
        BilibiliApi(fetcher=fetcher).pages("BV1xx411c7mD")
        assert "pagelist?bvid=BV1xx411c7mD" in fetcher.calls[0]

    def test_pages_cached_per_bvid(self):
        """分P展开和取流共享同一次 pagelist 请求。"""
        fetcher = PagelistFetcher(pagelist_response(TWO_PARTS))
        api = BilibiliApi(fetcher=fetcher)
        api.pages("BV1")
        api.pages("BV1")
        assert len(fetcher.calls) == 1

    def test_pages_error_code_raises(self):
        body = json.dumps({"code": -404, "message": "视频不存在"}).encode()
        api = BilibiliApi(fetcher=PagelistFetcher(body))
        with pytest.raises(BilibiliApiError, match="视频不存在"):
            api.pages("BV404")

    def test_pages_network_failure_raises(self):
        def boom(url, headers):
            raise OSError("timeout")

        with pytest.raises(BilibiliApiError):
            BilibiliApi(fetcher=boom).pages("BV1")


class TestAudioStream:
    AUDIOS = [
        {"id": 30216, "bandwidth": 65699, "baseUrl": "https://cdn/low.m4s"},
        {"id": 30280, "bandwidth": 228455, "baseUrl": "https://cdn/high.m4s"},
    ]

    def make_api(self, audios=None):
        return BilibiliApi(
            fetcher=RoutingFetcher(
                pagelist_response(TWO_PARTS),
                playurl_response(self.AUDIOS if audios is None else audios),
            )
        )

    def test_picks_highest_bandwidth_audio(self):
        stream = self.make_api().audio_stream("BV1", page=1)
        assert stream.url == "https://cdn/high.m4s"

    def test_headers_include_referer(self):
        stream = self.make_api().audio_stream("BV1", page=1)
        assert stream.headers["Referer"] == "https://www.bilibili.com/"
        assert "User-Agent" in stream.headers

    def test_uses_cid_of_requested_page(self):
        api = self.make_api()
        api.audio_stream("BV1", page=2)
        playurl_call = next(c for c in api._fetch.calls if "playurl" in c)
        assert "cid=222" in playurl_call

    def test_unknown_page_raises(self):
        with pytest.raises(BilibiliApiError, match="分P"):
            self.make_api().audio_stream("BV1", page=99)

    def test_no_audio_raises(self):
        with pytest.raises(BilibiliApiError, match="音频"):
            self.make_api(audios=[]).audio_stream("BV1", page=1)

    def test_snake_case_base_url_accepted(self):
        audios = [{"id": 1, "bandwidth": 100, "base_url": "https://cdn/snake.m4s"}]
        stream = self.make_api(audios=audios).audio_stream("BV1", page=1)
        assert stream.url == "https://cdn/snake.m4s"
