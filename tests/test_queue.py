"""Tests for the immutable play queue state machine."""
import pytest

from yueting.models import Source, Track
from yueting.player.queue import PlayMode, QueueState, add_tracks, clear, current_track, next_index, prev_index, remove_at


def t(n: int) -> Track:
    return Track(
        id=f"id{n}",
        source=Source.YOUTUBE,
        title=f"歌曲{n}",
        uploader="up",
        duration=100.0,
        webpage_url=f"https://example.com/{n}",
    )


@pytest.fixture
def q3() -> QueueState:
    return add_tracks(QueueState(), [t(1), t(2), t(3)])


class TestQueueBasics:
    def test_empty_queue_has_no_current(self):
        assert current_track(QueueState()) is None

    def test_add_tracks_returns_new_state(self):
        empty = QueueState()
        filled = add_tracks(empty, [t(1)])
        assert len(empty.tracks) == 0
        assert len(filled.tracks) == 1

    def test_add_skips_duplicates_by_key(self, q3):
        q = add_tracks(q3, [t(2)])
        assert len(q.tracks) == 3

    def test_current_track(self, q3):
        assert current_track(q3).id == "id1"

    def test_remove_at(self, q3):
        q = remove_at(q3, 0)
        assert [x.id for x in q.tracks] == ["id2", "id3"]

    def test_remove_before_current_keeps_current_track(self, q3):
        q = q3.with_index(2)
        q = remove_at(q, 0)
        assert current_track(q).id == "id3"

    def test_remove_current_last_track_moves_back(self, q3):
        q = q3.with_index(2)
        q = remove_at(q, 2)
        assert current_track(q).id == "id2"

    def test_clear(self, q3):
        q = clear(q3)
        assert len(q.tracks) == 0
        assert current_track(q) is None


class TestSequentialMode:
    def test_next_advances(self, q3):
        assert next_index(q3) == 1

    def test_next_at_end_stops(self, q3):
        q = q3.with_index(2)
        assert next_index(q) is None  # 顺序播放：播完停止

    def test_prev_at_start_stays(self, q3):
        assert prev_index(q3) == 0


class TestLoopModes:
    def test_loop_all_wraps(self, q3):
        q = q3.with_index(2).with_mode(PlayMode.LOOP_ALL)
        assert next_index(q) == 0

    def test_loop_all_prev_wraps(self, q3):
        q = q3.with_mode(PlayMode.LOOP_ALL)
        assert prev_index(q) == 2

    def test_loop_one_repeats_on_auto_advance(self, q3):
        q = q3.with_index(1).with_mode(PlayMode.LOOP_ONE)
        assert next_index(q, manual=False) == 1

    def test_loop_one_manual_next_advances(self, q3):
        q = q3.with_index(1).with_mode(PlayMode.LOOP_ONE)
        assert next_index(q, manual=True) == 2


class TestShuffleMode:
    def test_shuffle_next_stays_in_bounds_and_avoids_repeat(self, q3):
        q = q3.with_mode(PlayMode.SHUFFLE)
        for seed in range(20):
            idx = next_index(q, rng_seed=seed)
            assert idx in (1, 2)  # never repeats current index 0

    def test_shuffle_single_track_repeats(self):
        q = add_tracks(QueueState(), [t(1)]).with_mode(PlayMode.SHUFFLE)
        assert next_index(q, rng_seed=1) == 0


class TestPlayModeCycle:
    def test_cycle_order(self):
        assert PlayMode.SEQUENTIAL.cycled() == PlayMode.LOOP_ALL
        assert PlayMode.LOOP_ALL.cycled() == PlayMode.LOOP_ONE
        assert PlayMode.LOOP_ONE.cycled() == PlayMode.SHUFFLE
        assert PlayMode.SHUFFLE.cycled() == PlayMode.SEQUENTIAL

    def test_mode_display_chinese(self):
        assert PlayMode.SEQUENTIAL.display == "顺序"
        assert PlayMode.LOOP_ALL.display == "列表循环"
        assert PlayMode.LOOP_ONE.display == "单曲循环"
        assert PlayMode.SHUFFLE.display == "随机"
