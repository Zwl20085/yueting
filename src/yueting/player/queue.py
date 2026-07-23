"""播放队列：不可变状态 + 纯函数操作。"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from enum import Enum

from yueting.models import Track


class PlayMode(Enum):
    SEQUENTIAL = "sequential"
    LOOP_ALL = "loop_all"
    LOOP_ONE = "loop_one"
    SHUFFLE = "shuffle"

    @property
    def display(self) -> str:
        return {
            "sequential": "顺序",
            "loop_all": "列表循环",
            "loop_one": "单曲循环",
            "shuffle": "随机",
        }[self.value]

    def cycled(self) -> "PlayMode":
        order = [PlayMode.SEQUENTIAL, PlayMode.LOOP_ALL, PlayMode.LOOP_ONE, PlayMode.SHUFFLE]
        return order[(order.index(self) + 1) % len(order)]


@dataclass(frozen=True, slots=True)
class QueueState:
    tracks: tuple[Track, ...] = ()
    index: int = 0
    mode: PlayMode = PlayMode.SEQUENTIAL

    def with_index(self, index: int) -> "QueueState":
        return replace(self, index=index)

    def with_mode(self, mode: PlayMode) -> "QueueState":
        return replace(self, mode=mode)


def current_track(state: QueueState) -> Track | None:
    if not state.tracks or not (0 <= state.index < len(state.tracks)):
        return None
    return state.tracks[state.index]


def add_tracks(state: QueueState, tracks: list[Track]) -> QueueState:
    existing = {t.key for t in state.tracks}
    fresh = tuple(t for t in tracks if t.key not in existing)
    return replace(state, tracks=state.tracks + fresh)


def remove_at(state: QueueState, position: int) -> QueueState:
    if not (0 <= position < len(state.tracks)):
        return state
    tracks = state.tracks[:position] + state.tracks[position + 1 :]
    index = state.index
    if position < index:
        index -= 1
    index = max(0, min(index, len(tracks) - 1)) if tracks else 0
    return replace(state, tracks=tracks, index=index)


def clear(state: QueueState) -> QueueState:
    return replace(state, tracks=(), index=0)


def next_index(state: QueueState, manual: bool = True, rng_seed: int | None = None) -> int | None:
    """下一首的下标；顺序模式播到结尾返回 None（停止）。"""
    n = len(state.tracks)
    if n == 0:
        return None
    if state.mode is PlayMode.LOOP_ONE and not manual:
        return state.index
    if state.mode is PlayMode.SHUFFLE:
        if n == 1:
            return 0
        rng = random.Random(rng_seed)
        choices = [i for i in range(n) if i != state.index]
        return rng.choice(choices)
    if state.index + 1 < n:
        return state.index + 1
    if state.mode is PlayMode.LOOP_ALL:
        return 0
    return None


def prev_index(state: QueueState) -> int | None:
    n = len(state.tracks)
    if n == 0:
        return None
    if state.index - 1 >= 0:
        return state.index - 1
    if state.mode is PlayMode.LOOP_ALL:
        return n - 1
    return 0
