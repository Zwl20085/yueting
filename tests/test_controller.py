"""Tests for PlayerController — orchestrates queue, player, library, sources."""
import pytest

from yueting.controller import PlayerController
from yueting.models import Source, Track
from yueting.player.queue import PlayMode
from yueting.store.library import Library


def t(n: int) -> Track:
    return Track(
        id=f"id{n}",
        source=Source.BILIBILI,
        title=f"歌曲{n}",
        uploader="up",
        duration=100.0,
        webpage_url=f"https://example.com/{n}",
    )


class FakePlayer:
    def __init__(self):
        self.played: list[tuple[str, str]] = []
        self.played_headers: list[dict] = []
        self.paused_toggles = 0
        self.stopped = False
        self.volume_set: float | None = None

    def play(self, url, title="", headers=None):
        self.played.append((url, title))
        self.played_headers.append(headers or {})

    def toggle_pause(self):
        self.paused_toggles += 1

    def stop(self):
        self.stopped = True

    def set_volume(self, v):
        self.volume_set = v

    def seek(self, s):
        pass

    def position(self):
        return 1.0

    def duration(self):
        return 100.0

    def is_paused(self):
        return False

    def close(self):
        pass


class FakeSource:
    def __init__(self):
        self.resolved: list[str] = []

    def resolve_stream_url(self, webpage_url: str):
        from yueting.sources.ytdlp_source import StreamInfo

        self.resolved.append(webpage_url)
        return StreamInfo(url=f"stream://{webpage_url}", headers={"Referer": "https://r/"})

    def search(self, query, source, limit=10):
        return [t(1), t(2)]


@pytest.fixture
def controller(tmp_path):
    lib = Library(tmp_path / "db.sqlite")
    ctrl = PlayerController(player=FakePlayer(), source=FakeSource(), library=lib, clock=lambda: 1234.5)
    yield ctrl
    lib.close()


class TestPlayback:
    def test_play_now_resolves_stream_and_plays(self, controller):
        controller.play_now([t(1), t(2)], start=0)
        assert controller.player.played == [("stream://https://example.com/1", "歌曲1")]
        assert controller.current.id == "id1"

    def test_play_passes_stream_headers_to_player(self, controller):
        controller.play_now([t(1)], start=0)
        assert controller.player.played_headers == [{"Referer": "https://r/"}]

    def test_play_records_history(self, controller):
        controller.play_now([t(1)], start=0)
        rows = controller.library.history(limit=5)
        assert rows[0].track.id == "id1"
        assert rows[0].played_at == 1234.5

    def test_next_advances_and_plays(self, controller):
        controller.play_now([t(1), t(2)], start=0)
        controller.next()
        assert controller.current.id == "id2"
        assert len(controller.player.played) == 2

    def test_next_at_end_sequential_stops(self, controller):
        controller.play_now([t(1)], start=0)
        controller.next()
        assert controller.player.stopped is True

    def test_prev(self, controller):
        controller.play_now([t(1), t(2)], start=1)
        controller.prev()
        assert controller.current.id == "id1"

    def test_enqueue_appends_without_interrupting(self, controller):
        controller.play_now([t(1)], start=0)
        controller.enqueue([t(2)])
        assert len(controller.queue.tracks) == 2
        assert len(controller.player.played) == 1

    def test_cycle_mode(self, controller):
        assert controller.queue.mode is PlayMode.SEQUENTIAL
        controller.cycle_mode()
        assert controller.queue.mode is PlayMode.LOOP_ALL

    def test_stream_url_cached_within_ttl(self, controller):
        """同一曲目短时间内重复播放不重复取流。"""
        controller.play_now([t(1), t(2)], start=0)
        controller.next()
        controller.prev()  # 回到 t(1)，应命中缓存
        assert controller.source.resolved.count("https://example.com/1") == 1

    def test_stream_cache_expires(self, tmp_path):
        lib = Library(tmp_path / "db2.sqlite")
        clock = [1000.0]
        ctrl = PlayerController(
            player=FakePlayer(), source=FakeSource(), library=lib,
            clock=lambda: clock[0], stream_ttl=100,
        )
        ctrl.play_now([t(1)], start=0)
        clock[0] += 200  # 缓存过期
        ctrl.play_at(0)
        assert ctrl.source.resolved.count("https://example.com/1") == 2
        lib.close()

    def test_prefetch_next_fills_cache(self, controller):
        """预取下一首后，next() 无需再次取流，切歌零等待。"""
        controller.play_now([t(1), t(2)], start=0)
        controller.prefetch_next()
        assert "https://example.com/2" in controller.source.resolved
        controller.next()
        assert controller.source.resolved.count("https://example.com/2") == 1

    def test_prefetch_next_at_queue_end_is_noop(self, controller):
        controller.play_now([t(1)], start=0)
        controller.prefetch_next()  # 顺序模式最后一首，没有下一首
        assert controller.source.resolved == ["https://example.com/1"]

    def test_prefetch_error_is_silent(self, controller):
        controller.play_now([t(1), t(2)], start=0)

        def boom(url):
            raise RuntimeError("网络抖动")

        controller.source.resolve_stream_url = boom
        controller.prefetch_next()  # 不应抛异常，也不应触发 on_error 弹窗

    def test_stream_resolve_failure_skips_gracefully(self, controller):
        def boom(url):
            raise RuntimeError("取流失败")

        controller.source.resolve_stream_url = boom
        errors = []
        controller.on_error = errors.append
        controller.play_now([t(1)], start=0)
        assert controller.player.played == []
        assert errors  # 错误上报给 UI 而不是崩溃
