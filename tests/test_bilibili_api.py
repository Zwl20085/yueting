"""Tests for the fast Bilibili search API client (fetcher injected, no network)."""
import json

import pytest

from yueting.models import Source
from yueting.sources.bilibili_api import (
    BilibiliApi,
    BilibiliApiError,
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
