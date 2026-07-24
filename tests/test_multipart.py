"""Tests for Bilibili 分P (multi-part) expansion: 50P 合集 becomes a 50-song queue."""
import pytest

from yueting.models import Source, Track
from yueting.player.queue import QueueState, add_tracks, current_track, replace_at
from yueting.sources.bilibili_api import BilibiliApiError, VideoPage
from yueting.sources.ytdlp_source import YtdlpSource


def bili_track(bvid="BV1FPjy6TEiE", title="【周杰伦】50首精选", url=None):
    return Track(
        id=bvid,
        source=Source.BILIBILI,
        title=title,
        uploader="up",
        duration=None,
        webpage_url=url or f"https://www.bilibili.com/video/{bvid}",
    )


def yt_track():
    return Track(
        id="ytid", source=Source.YOUTUBE, title="song",
        webpage_url="https://youtube.com/watch?v=ytid",
    )


class FakeApi:
    def __init__(self, pages):
        self._pages = tuple(pages)
        self.calls = 0

    def pages(self, bvid):
        self.calls += 1
        if isinstance(self._pages, Exception):
            raise self._pages
        return self._pages

    def search(self, query, limit=20):
        return []


TWO_PAGES = (
    VideoPage(page=1, title="001.晴天", duration=270.0, cid=111),
    VideoPage(page=2, title="002.夜曲", duration=227.0, cid=222),
)


class TestExpandParts:
    def test_multipart_expands_to_part_tracks(self):
        src = YtdlpSource(bili_api=FakeApi(TWO_PAGES))
        parts = src.expand_parts(bili_track())
        assert len(parts) == 2
        assert parts[0].title == "001.晴天"
        assert parts[0].duration == 270.0
        assert parts[0].webpage_url.endswith("?p=1")
        assert parts[1].webpage_url.endswith("?p=2")
        # 每个分P必须有独立 key，歌单/收藏/历史才不会串
        assert parts[0].key != parts[1].key

    def test_part_uploader_inherited(self):
        src = YtdlpSource(bili_api=FakeApi(TWO_PAGES))
        assert src.expand_parts(bili_track())[0].uploader == "up"

    def test_single_part_returns_original(self):
        src = YtdlpSource(bili_api=FakeApi((VideoPage(page=1, title="x", duration=1.0, cid=1),)))
        track = bili_track()
        assert src.expand_parts(track) == [track]

    def test_part_track_not_reexpanded(self):
        """已经是 ?p=N 的分P曲目不再展开（防死循环）。"""
        api = FakeApi(TWO_PAGES)
        src = YtdlpSource(bili_api=api)
        part = bili_track(url="https://www.bilibili.com/video/BV1?p=2")
        assert src.expand_parts(part) == [part]
        assert api.calls == 0

    def test_youtube_track_not_expanded(self):
        api = FakeApi(TWO_PAGES)
        src = YtdlpSource(bili_api=api)
        track = yt_track()
        assert src.expand_parts(track) == [track]
        assert api.calls == 0

    def test_api_error_falls_back_to_original(self):
        class BoomApi:
            def pages(self, bvid):
                raise BilibiliApiError("接口异常")

        src = YtdlpSource(bili_api=BoomApi())
        track = bili_track()
        assert src.expand_parts(track) == [track]

    def test_expansion_cached_per_bvid(self):
        api = FakeApi(TWO_PAGES)
        src = YtdlpSource(bili_api=api)
        src.expand_parts(bili_track())
        src.expand_parts(bili_track())
        assert api.calls == 1

    def test_blank_part_title_falls_back_to_numbered(self):
        pages = (
            VideoPage(page=1, title="", duration=1.0, cid=1),
            VideoPage(page=2, title=" ", duration=2.0, cid=2),
        )
        src = YtdlpSource(bili_api=FakeApi(pages))
        parts = src.expand_parts(bili_track(title="合集"))
        assert parts[0].title == "合集 P1"
        assert parts[1].title == "合集 P2"


class TestQueueReplaceAt:
    def t(self, n):
        return Track(id=f"id{n}", source=Source.YOUTUBE, title=f"歌{n}", webpage_url=f"u{n}")

    def test_replace_at_splices_tracks(self):
        state = add_tracks(QueueState(), [self.t(1), self.t(2), self.t(3)])
        state = replace_at(state, 1, [self.t(4), self.t(5)])
        assert [x.id for x in state.tracks] == ["id1", "id4", "id5", "id3"]

    def test_replace_at_current_keeps_index_on_first_new(self):
        state = add_tracks(QueueState(), [self.t(1), self.t(2)]).with_index(1)
        state = replace_at(state, 1, [self.t(4), self.t(5)])
        assert current_track(state).id == "id4"

    def test_replace_after_current_keeps_current(self):
        state = add_tracks(QueueState(), [self.t(1), self.t(2)]).with_index(0)
        state = replace_at(state, 1, [self.t(4), self.t(5)])
        assert current_track(state).id == "id1"

    def test_replace_before_current_shifts_index(self):
        state = add_tracks(QueueState(), [self.t(1), self.t(2)]).with_index(1)
        state = replace_at(state, 0, [self.t(4), self.t(5)])
        assert current_track(state).id == "id2"

    def test_replace_out_of_range_is_noop(self):
        state = add_tracks(QueueState(), [self.t(1)])
        assert replace_at(state, 5, [self.t(4)]) == state


class TestControllerExpansion:
    @pytest.fixture
    def controller(self, tmp_path):
        from yueting.controller import PlayerController
        from yueting.sources.ytdlp_source import StreamInfo
        from yueting.store.library import Library

        class FakePlayer:
            def __init__(self):
                self.played = []

            def play(self, url, title="", headers=None):
                self.played.append((url, title))

            def toggle_pause(self): ...
            def stop(self): ...
            def seek(self, s): ...
            def set_volume(self, v): ...
            def position(self): return 0.0
            def duration(self): return 100.0
            def is_paused(self): return False
            def close(self): ...

        class ExpandingSource:
            def __init__(self):
                self.resolved = []

            def expand_parts(self, track):
                if track.source is Source.BILIBILI and "?p=" not in track.webpage_url:
                    return [
                        Track(id=f"{track.id}-p{p.page}", source=Source.BILIBILI,
                              title=p.title, uploader=track.uploader, duration=p.duration,
                              webpage_url=f"{track.webpage_url}?p={p.page}")
                        for p in TWO_PAGES
                    ]
                return [track]

            def resolve_stream_url(self, url):
                self.resolved.append(url)
                return StreamInfo(url=f"stream://{url}")

            def search(self, query, source, limit=10):
                return []

        lib = Library(tmp_path / "db.sqlite")
        ctrl = PlayerController(
            player=FakePlayer(), source=ExpandingSource(), library=lib, clock=lambda: 1.0
        )
        yield ctrl
        lib.close()

    def test_playing_multipart_expands_queue(self, controller):
        controller.play_now([bili_track(), yt_track()], start=0)
        assert len(controller.queue.tracks) == 3  # 2 parts + youtube track
        assert controller.current.title == "001.晴天"
        assert controller.player.played[-1][1] == "001.晴天"

    def test_next_moves_to_second_part(self, controller):
        controller.play_now([bili_track()], start=0)
        controller.next()
        assert controller.current.title == "002.夜曲"

    def test_notice_callback_reports_expansion(self, controller):
        notices = []
        controller.on_notice = notices.append
        controller.play_now([bili_track()], start=0)
        assert any("2" in n and "分P" in n for n in notices)

    def test_single_track_no_notice(self, controller):
        notices = []
        controller.on_notice = notices.append
        controller.play_now([yt_track()], start=0)
        assert notices == []
