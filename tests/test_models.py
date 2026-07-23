"""Tests for core domain models (RED first)."""
import dataclasses

import pytest

from yueting.models import Source, Track


def make_track(**overrides):
    base = dict(
        id="BV1xx411c7mD",
        source=Source.BILIBILI,
        title="周杰伦 - 晴天",
        uploader="某UP主",
        duration=269.0,
        webpage_url="https://www.bilibili.com/video/BV1xx411c7mD",
    )
    base.update(overrides)
    return Track(**base)


class TestTrack:
    def test_track_is_immutable(self):
        track = make_track()
        with pytest.raises(dataclasses.FrozenInstanceError):
            track.title = "改名"

    def test_track_key_is_source_scoped(self):
        """Same video id on different sources must not collide."""
        t1 = make_track(source=Source.BILIBILI)
        t2 = make_track(source=Source.YOUTUBE)
        assert t1.key != t2.key
        assert t1.key == "bilibili:BV1xx411c7mD"

    def test_duration_display_formats_mm_ss(self):
        assert make_track(duration=269.0).duration_display == "04:29"
        assert make_track(duration=0).duration_display == "00:00"
        assert make_track(duration=None).duration_display == "--:--"

    def test_duration_display_formats_over_an_hour(self):
        assert make_track(duration=3725).duration_display == "1:02:05"

    def test_rejects_blank_title(self):
        with pytest.raises(ValueError):
            make_track(title="   ")

    def test_rejects_blank_id(self):
        with pytest.raises(ValueError):
            make_track(id="")


class TestSource:
    def test_source_values(self):
        assert Source.YOUTUBE.value == "youtube"
        assert Source.BILIBILI.value == "bilibili"

    def test_source_display_names_are_chinese(self):
        assert Source.BILIBILI.display == "B站"
        assert Source.YOUTUBE.display == "油管"
