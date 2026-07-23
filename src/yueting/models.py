"""核心领域模型：不可变数据结构。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Source(Enum):
    YOUTUBE = "youtube"
    BILIBILI = "bilibili"

    @property
    def display(self) -> str:
        return {"youtube": "油管", "bilibili": "B站"}[self.value]


@dataclass(frozen=True, slots=True)
class Track:
    id: str
    source: Source
    title: str
    uploader: str = ""
    duration: float | None = None
    webpage_url: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Track.id 不能为空")
        if not self.title.strip():
            raise ValueError("Track.title 不能为空")

    @property
    def key(self) -> str:
        """跨音乐源唯一标识。"""
        return f"{self.source.value}:{self.id}"

    @property
    def duration_display(self) -> str:
        if self.duration is None:
            return "--:--"
        total = int(self.duration)
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


@dataclass(frozen=True, slots=True)
class Playlist:
    id: int
    name: str
    track_count: int = 0


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    track: Track
    played_at: float
