"""Tests for search sources (yt-dlp backed, fully mocked — no network)."""
from unittest.mock import MagicMock, patch

import pytest

from yueting.models import Source
from yueting.sources.ytdlp_source import SearchError, StreamInfo, YtdlpSource, _entry_to_track


def fake_entry(**overrides):
    base = {
        "id": "BV1xx411c7mD",
        "title": "周杰伦 - 晴天 (官方MV)",
        "uploader": "杰威尔音乐",
        "duration": 269,
        "webpage_url": "https://www.bilibili.com/video/BV1xx411c7mD",
    }
    base.update(overrides)
    return base


class TestEntryToTrack:
    def test_maps_fields(self):
        track = _entry_to_track(fake_entry(), Source.BILIBILI)
        assert track.id == "BV1xx411c7mD"
        assert track.title == "周杰伦 - 晴天 (官方MV)"
        assert track.uploader == "杰威尔音乐"
        assert track.duration == 269
        assert track.source == Source.BILIBILI

    def test_skips_entry_without_id(self):
        assert _entry_to_track(fake_entry(id=None), Source.BILIBILI) is None

    def test_tolerates_missing_optional_fields(self):
        entry = {"id": "abc", "title": "标题"}
        track = _entry_to_track(entry, Source.YOUTUBE)
        assert track.uploader == ""
        assert track.duration is None
        assert track.webpage_url == ""


class BrokenBiliApi:
    """强制 YtdlpSource 走 yt-dlp 兜底路径。"""

    def _boom(self):
        from yueting.sources.bilibili_api import BilibiliApiError

        raise BilibiliApiError("test: api down")

    def search(self, query, limit=20):
        self._boom()

    def pages(self, bvid):
        self._boom()

    def audio_stream(self, bvid, page=1):
        self._boom()


class TestSearch:
    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_bilibili_uses_bilisearch_prefix(self, mock_ydl_cls):
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {"entries": [fake_entry()]}

        src = YtdlpSource(bili_api=BrokenBiliApi())
        results = src.search("晴天", Source.BILIBILI, limit=10)

        query = instance.extract_info.call_args[0][0]
        assert query == "bilisearch10:晴天"
        assert len(results) == 1
        assert results[0].source == Source.BILIBILI

    def test_bilibili_prefers_fast_api(self):
        """B站搜索优先走官方 API（~1s），完全不碰 yt-dlp。"""
        from yueting.models import Track

        class FakeApi:
            def search(self, query, limit=20):
                return [Track(id="BV1", source=Source.BILIBILI, title="晴天",
                              webpage_url="https://www.bilibili.com/video/BV1")]

        src = YtdlpSource(bili_api=FakeApi())
        with patch("yueting.sources.ytdlp_source._ydl_class") as mock_ydl:
            results = src.search("晴天", Source.BILIBILI)
        assert len(results) == 1
        mock_ydl.assert_not_called()

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_bilibili_falls_back_to_ytdlp_when_api_fails(self, mock_ydl_cls):
        from yueting.sources.bilibili_api import BilibiliApiError

        class BrokenApi:
            def search(self, query, limit=20):
                raise BilibiliApiError("接口挂了")

        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {"entries": [fake_entry()]}
        src = YtdlpSource(bili_api=BrokenApi())
        results = src.search("晴天", Source.BILIBILI)
        assert len(results) == 1  # yt-dlp 兜底成功

    def test_search_results_are_cached(self):
        """相同搜索词 10 分钟内直接命中缓存。"""
        from yueting.models import Track

        class CountingApi:
            def __init__(self):
                self.calls = 0

            def search(self, query, limit=20):
                self.calls += 1
                return [Track(id="BV1", source=Source.BILIBILI, title="晴天",
                              webpage_url="https://x/1")]

        api = CountingApi()
        clock = [1000.0]
        src = YtdlpSource(bili_api=api, clock=lambda: clock[0])
        src.search("晴天", Source.BILIBILI)
        src.search("晴天", Source.BILIBILI)
        assert api.calls == 1
        clock[0] += 601  # 缓存过期
        src.search("晴天", Source.BILIBILI)
        assert api.calls == 2

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_bilibili_search_sends_browser_headers_and_ignores_bad_entries(self, mock_ydl_cls):
        """B站搜索接口无浏览器 UA 会 412；含付费课程条目须跳过而非中断。"""
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {"entries": [fake_entry()]}

        YtdlpSource(bili_api=BrokenBiliApi()).search("晴天", Source.BILIBILI)

        opts = mock_ydl_cls.call_args[0][0]
        assert "Mozilla" in opts["http_headers"]["User-Agent"]
        assert opts["http_headers"]["Referer"] == "https://www.bilibili.com/"
        assert opts["ignoreerrors"] is True
        # B站 flat 搜索拿不到标题，必须完整解析
        assert not opts.get("extract_flat")

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_youtube_search_stays_flat_for_speed(self, mock_ydl_cls):
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {"entries": [fake_entry()]}

        YtdlpSource().search("晴天", Source.YOUTUBE)

        opts = mock_ydl_cls.call_args[0][0]
        assert opts.get("extract_flat")

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_youtube_uses_ytsearch_prefix(self, mock_ydl_cls):
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {"entries": [fake_entry()]}

        src = YtdlpSource()
        src.search("晴天", Source.YOUTUBE, limit=5)

        assert instance.extract_info.call_args[0][0] == "ytsearch5:晴天"

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_filters_none_entries(self, mock_ydl_cls):
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {
            "entries": [fake_entry(), None, fake_entry(id=None)]
        }
        results = YtdlpSource(bili_api=BrokenBiliApi()).search("晴天", Source.BILIBILI)
        assert len(results) == 1

    def test_blank_query_raises(self):
        with pytest.raises(ValueError):
            YtdlpSource().search("   ", Source.BILIBILI)

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_extractor_failure_wrapped_in_search_error(self, mock_ydl_cls):
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.side_effect = RuntimeError("network down")
        with pytest.raises(SearchError, match="搜索失败"):
            YtdlpSource(bili_api=BrokenBiliApi()).search("晴天", Source.BILIBILI)


class TestBilibiliFastResolve:
    """B站取流优先走 playurl API（~1s），yt-dlp 只做兜底（~5s）。"""

    def make_source(self, api):
        return YtdlpSource(bili_api=api)

    def test_bilibili_url_resolved_via_api(self):
        class FastApi:
            def __init__(self):
                self.calls = []

            def audio_stream(self, bvid, page=1):
                self.calls.append((bvid, page))
                return StreamInfo(url="https://cdn/a.m4s", headers={"Referer": "https://r/"})

        api = FastApi()
        src = self.make_source(api)
        with patch("yueting.sources.ytdlp_source._ydl_class") as mock_ydl:
            stream = src.resolve_stream_url("https://www.bilibili.com/video/BV1xx411c7mD")
        assert stream.url == "https://cdn/a.m4s"
        assert api.calls == [("BV1xx411c7mD", 1)]
        mock_ydl.assert_not_called()

    def test_part_url_passes_page_number(self):
        class FastApi:
            def __init__(self):
                self.calls = []

            def audio_stream(self, bvid, page=1):
                self.calls.append((bvid, page))
                return StreamInfo(url="https://cdn/a.m4s")

        api = FastApi()
        self.make_source(api).resolve_stream_url("https://www.bilibili.com/video/BV1abc?p=7")
        assert api.calls == [("BV1abc", 7)]

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_api_failure_falls_back_to_ytdlp(self, mock_ydl_cls):
        from yueting.sources.bilibili_api import BilibiliApiError

        class BoomApi:
            def audio_stream(self, bvid, page=1):
                raise BilibiliApiError("接口异常")

        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {"url": "https://cdn/fallback.m4a"}
        stream = self.make_source(BoomApi()).resolve_stream_url(
            "https://www.bilibili.com/video/BV1xx411c7mD"
        )
        assert stream.url == "https://cdn/fallback.m4a"

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_non_bilibili_url_uses_ytdlp(self, mock_ydl_cls):
        class NeverApi:
            def audio_stream(self, bvid, page=1):  # pragma: no cover
                raise AssertionError("油管取流不应走B站API")

        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {"url": "https://cdn/yt.m4a"}
        stream = self.make_source(NeverApi()).resolve_stream_url(
            "https://www.youtube.com/watch?v=abc"
        )
        assert stream.url == "https://cdn/yt.m4a"


class TestStreamUrl:
    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_resolve_stream_url_prefers_audio(self, mock_ydl_cls):
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {"url": "https://cdn.example.com/audio.m4a"}

        src = YtdlpSource(bili_api=BrokenBiliApi())
        stream = src.resolve_stream_url("https://www.bilibili.com/video/BV1xx411c7mD")
        assert stream.url == "https://cdn.example.com/audio.m4a"

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_resolve_returns_http_headers_for_player(self, mock_ydl_cls):
        """B站 CDN 无 Referer 会 403，播放器必须带上 yt-dlp 给的请求头。"""
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {
            "url": "https://cdn.example.com/audio.m4a",
            "http_headers": {"Referer": "https://www.bilibili.com/", "User-Agent": "UA"},
        }
        stream = YtdlpSource(bili_api=BrokenBiliApi()).resolve_stream_url(
            "https://www.bilibili.com/video/BV1xx411c7mD"
        )
        assert isinstance(stream, StreamInfo)
        assert stream.headers["Referer"] == "https://www.bilibili.com/"

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_resolve_falls_back_to_format_headers(self, mock_ydl_cls):
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {
            "formats": [
                {"acodec": "mp4a", "url": "https://cdn.example.com/a.m4a",
                 "http_headers": {"Referer": "https://r/"}}
            ]
        }
        stream = YtdlpSource().resolve_stream_url("https://x")
        assert stream.url == "https://cdn.example.com/a.m4a"
        assert stream.headers == {"Referer": "https://r/"}

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_resolve_failure_raises_search_error(self, mock_ydl_cls):
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.side_effect = RuntimeError("boom")
        with pytest.raises(SearchError):
            YtdlpSource().resolve_stream_url("https://bad.example.com")
