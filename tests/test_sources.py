"""Tests for search sources (yt-dlp backed, fully mocked — no network)."""
from unittest.mock import MagicMock, patch

import pytest

from yueting.models import Source
from yueting.sources.ytdlp_source import SearchError, YtdlpSource, _entry_to_track


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


class TestSearch:
    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_bilibili_uses_bilisearch_prefix(self, mock_ydl_cls):
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {"entries": [fake_entry()]}

        src = YtdlpSource()
        results = src.search("晴天", Source.BILIBILI, limit=10)

        query = instance.extract_info.call_args[0][0]
        assert query == "bilisearch10:晴天"
        assert len(results) == 1
        assert results[0].source == Source.BILIBILI

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
        results = YtdlpSource().search("晴天", Source.BILIBILI)
        assert len(results) == 1

    def test_blank_query_raises(self):
        with pytest.raises(ValueError):
            YtdlpSource().search("   ", Source.BILIBILI)

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_extractor_failure_wrapped_in_search_error(self, mock_ydl_cls):
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.side_effect = RuntimeError("network down")
        with pytest.raises(SearchError, match="搜索失败"):
            YtdlpSource().search("晴天", Source.BILIBILI)


class TestStreamUrl:
    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_resolve_stream_url_prefers_audio(self, mock_ydl_cls):
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.return_value = {"url": "https://cdn.example.com/audio.m4a"}

        src = YtdlpSource()
        url = src.resolve_stream_url("https://www.bilibili.com/video/BV1xx411c7mD")
        assert url == "https://cdn.example.com/audio.m4a"

    @patch("yueting.sources.ytdlp_source.YoutubeDL")
    def test_resolve_failure_raises_search_error(self, mock_ydl_cls):
        instance = mock_ydl_cls.return_value.__enter__.return_value
        instance.extract_info.side_effect = RuntimeError("boom")
        with pytest.raises(SearchError):
            YtdlpSource().resolve_stream_url("https://bad.example.com")
