"""播放控制器：连接队列、播放器、曲库与音乐源，UI 只与它交互。"""
from __future__ import annotations

import time
from typing import Callable

from yueting.models import Track
from yueting.player import queue as q
from yueting.player.queue import QueueState


class PlayerController:
    def __init__(self, player, source, library, clock: Callable[[], float] = time.time) -> None:
        self.player = player
        self.source = source
        self.library = library
        self.queue: QueueState = QueueState()
        self._clock = clock
        self.on_error: Callable[[str], None] = lambda msg: None
        self.on_track_change: Callable[[Track | None], None] = lambda track: None

    @property
    def current(self) -> Track | None:
        return q.current_track(self.queue)

    # -- queue operations --------------------------------------------------
    def play_now(self, tracks: list[Track], start: int = 0) -> None:
        """用给定曲目替换队列并从 start 开始播放。"""
        self.queue = q.add_tracks(q.clear(self.queue), tracks).with_index(start)
        self._play_current()

    def enqueue(self, tracks: list[Track]) -> None:
        self.queue = q.add_tracks(self.queue, tracks)

    def next(self, manual: bool = True) -> None:
        idx = q.next_index(self.queue, manual=manual)
        if idx is None:
            self.player.stop()
            self.on_track_change(None)
            return
        self.queue = self.queue.with_index(idx)
        self._play_current()

    def prev(self) -> None:
        idx = q.prev_index(self.queue)
        if idx is None:
            return
        self.queue = self.queue.with_index(idx)
        self._play_current()

    def play_at(self, index: int) -> None:
        if 0 <= index < len(self.queue.tracks):
            self.queue = self.queue.with_index(index)
            self._play_current()

    def cycle_mode(self) -> None:
        self.queue = self.queue.with_mode(self.queue.mode.cycled())

    # -- playback ------------------------------------------------------------
    def _play_current(self) -> None:
        track = self.current
        if track is None:
            return
        try:
            stream = self.source.resolve_stream_url(track.webpage_url)
        except Exception as exc:
            self.on_error(f"无法播放「{track.title}」：{exc}")
            return
        self.player.play(stream.url, title=track.title, headers=stream.headers)
        self.library.record_play(track, at=self._clock())
        self.on_track_change(track)

    def toggle_pause(self) -> None:
        self.player.toggle_pause()

    def seek(self, seconds: float) -> None:
        self.player.seek(seconds)

    def set_volume(self, volume: float) -> None:
        self.player.set_volume(volume)

    def close(self) -> None:
        self.player.close()
        self.library.close()
