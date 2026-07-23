"""本地曲库：SQLite 存储歌单、收藏、播放历史 (Repository 模式)。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from yueting.models import HistoryEntry, Playlist, Source, Track

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    video_id TEXT NOT NULL,
    title TEXT NOT NULL,
    uploader TEXT NOT NULL DEFAULT '',
    duration REAL,
    webpage_url TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec'))
);
CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    track_key TEXT NOT NULL REFERENCES tracks(key),
    position INTEGER NOT NULL,
    PRIMARY KEY (playlist_id, track_key)
);
CREATE TABLE IF NOT EXISTS favorites (
    track_key TEXT PRIMARY KEY REFERENCES tracks(key),
    added_at REAL NOT NULL DEFAULT (unixepoch('subsec'))
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_key TEXT NOT NULL REFERENCES tracks(key),
    played_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_time ON history(played_at DESC);
"""


def _row_to_track(row: sqlite3.Row) -> Track:
    return Track(
        id=row["video_id"],
        source=Source(row["source"]),
        title=row["title"],
        uploader=row["uploader"],
        duration=row["duration"],
        webpage_url=row["webpage_url"],
    )


class Library:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- internal ---------------------------------------------------------
    def _upsert_track(self, track: Track) -> None:
        self._conn.execute(
            """INSERT INTO tracks (key, source, video_id, title, uploader, duration, webpage_url)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   title = excluded.title,
                   uploader = excluded.uploader,
                   duration = excluded.duration,
                   webpage_url = excluded.webpage_url""",
            (track.key, track.source.value, track.id, track.title,
             track.uploader, track.duration, track.webpage_url),
        )

    # -- playlists ---------------------------------------------------------
    def create_playlist(self, name: str) -> Playlist:
        name = name.strip()
        if not name:
            raise ValueError("歌单名不能为空")
        try:
            cur = self._conn.execute("INSERT INTO playlists (name) VALUES (?)", (name,))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"歌单「{name}」已存在") from exc
        self._conn.commit()
        return Playlist(id=cur.lastrowid, name=name, track_count=0)

    def playlists(self) -> list[Playlist]:
        rows = self._conn.execute(
            """SELECT p.id, p.name, COUNT(pt.track_key) AS n
               FROM playlists p
               LEFT JOIN playlist_tracks pt ON pt.playlist_id = p.id
               GROUP BY p.id ORDER BY p.created_at, p.id"""
        ).fetchall()
        return [Playlist(id=r["id"], name=r["name"], track_count=r["n"]) for r in rows]

    def rename_playlist(self, playlist_id: int, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("歌单名不能为空")
        try:
            self._conn.execute("UPDATE playlists SET name = ? WHERE id = ?", (new_name, playlist_id))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"歌单「{new_name}」已存在") from exc
        self._conn.commit()

    def delete_playlist(self, playlist_id: int) -> None:
        self._conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        self._conn.commit()

    def add_to_playlist(self, playlist_id: int, track: Track) -> None:
        self._upsert_track(track)
        self._conn.execute(
            """INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_key, position)
               VALUES (?, ?, COALESCE(
                   (SELECT MAX(position) + 1 FROM playlist_tracks WHERE playlist_id = ?), 0))""",
            (playlist_id, track.key, playlist_id),
        )
        self._conn.commit()

    def remove_from_playlist(self, playlist_id: int, track_key: str) -> None:
        self._conn.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id = ? AND track_key = ?",
            (playlist_id, track_key),
        )
        self._conn.commit()

    def playlist_tracks(self, playlist_id: int) -> list[Track]:
        rows = self._conn.execute(
            """SELECT t.* FROM playlist_tracks pt
               JOIN tracks t ON t.key = pt.track_key
               WHERE pt.playlist_id = ? ORDER BY pt.position""",
            (playlist_id,),
        ).fetchall()
        return [_row_to_track(r) for r in rows]

    # -- favorites -----------------------------------------------------------
    def toggle_favorite(self, track: Track) -> bool:
        """收藏/取消收藏；返回操作后的收藏状态。"""
        if self.is_favorite(track.key):
            self._conn.execute("DELETE FROM favorites WHERE track_key = ?", (track.key,))
            self._conn.commit()
            return False
        self._upsert_track(track)
        self._conn.execute("INSERT INTO favorites (track_key) VALUES (?)", (track.key,))
        self._conn.commit()
        return True

    def is_favorite(self, track_key: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM favorites WHERE track_key = ?", (track_key,)
        ).fetchone()
        return row is not None

    def favorites(self) -> list[Track]:
        rows = self._conn.execute(
            """SELECT t.* FROM favorites f JOIN tracks t ON t.key = f.track_key
               ORDER BY f.added_at DESC"""
        ).fetchall()
        return [_row_to_track(r) for r in rows]

    # -- history --------------------------------------------------------------
    def record_play(self, track: Track, at: float) -> None:
        self._upsert_track(track)
        self._conn.execute(
            "INSERT INTO history (track_key, played_at) VALUES (?, ?)", (track.key, at)
        )
        self._conn.commit()

    def history(self, limit: int = 100) -> list[HistoryEntry]:
        rows = self._conn.execute(
            """SELECT t.*, h.played_at FROM history h
               JOIN tracks t ON t.key = h.track_key
               ORDER BY h.played_at DESC, h.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [HistoryEntry(track=_row_to_track(r), played_at=r["played_at"]) for r in rows]

    def play_counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT track_key, COUNT(*) AS n FROM history GROUP BY track_key"
        ).fetchall()
        return {r["track_key"]: r["n"] for r in rows}
