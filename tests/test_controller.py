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
        self.paused_toggles = 0
        self.stopped = False
        self.volume_set: float | None = None

    def play(self, url, title=""):
        self.played.append((url, title))

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

    def resolve_stream_url(self, webpage_url: str) -> str:
        self.resolved.append(webpage_url)
        return f"stream://{webpage_url}"

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

    def test_stream_resolve_failure_skips_gracefully(self, controller):
        def boom(url):
            raise RuntimeError("取流失败")

        controller.source.resolve_stream_url = boom
        errors = []
        controller.on_error = errors.append
        controller.play_now([t(1)], start=0)
        assert controller.player.played == []
        assert errors  # 错误上报给 UI 而不是崩溃
