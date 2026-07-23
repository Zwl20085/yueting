"""Tests for the SQLite-backed library store (playlists 歌单, favorites, history)."""
import pytest

from yueting.models import Source, Track
from yueting.store.library import Library


def t(n: int, uploader: str = "up", source: Source = Source.BILIBILI) -> Track:
    return Track(
        id=f"id{n}",
        source=source,
        title=f"歌曲{n}",
        uploader=uploader,
        duration=100.0 + n,
        webpage_url=f"https://example.com/{n}",
    )


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "yueting.db")
    yield library
    library.close()


class TestPlaylists:
    def test_create_and_list_playlists(self, lib):
        lib.create_playlist("华语经典")
        lib.create_playlist("学习BGM")
        assert [p.name for p in lib.playlists()] == ["华语经典", "学习BGM"]

    def test_create_duplicate_name_raises(self, lib):
        lib.create_playlist("华语经典")
        with pytest.raises(ValueError, match="已存在"):
            lib.create_playlist("华语经典")

    def test_create_blank_name_raises(self, lib):
        with pytest.raises(ValueError):
            lib.create_playlist("  ")

    def test_add_and_get_tracks(self, lib):
        p = lib.create_playlist("华语经典")
        lib.add_to_playlist(p.id, t(1))
        lib.add_to_playlist(p.id, t(2))
        tracks = lib.playlist_tracks(p.id)
        assert [x.title for x in tracks] == ["歌曲1", "歌曲2"]

    def test_add_duplicate_track_is_idempotent(self, lib):
        p = lib.create_playlist("华语经典")
        lib.add_to_playlist(p.id, t(1))
        lib.add_to_playlist(p.id, t(1))
        assert len(lib.playlist_tracks(p.id)) == 1

    def test_remove_track(self, lib):
        p = lib.create_playlist("华语经典")
        lib.add_to_playlist(p.id, t(1))
        lib.remove_from_playlist(p.id, t(1).key)
        assert lib.playlist_tracks(p.id) == []

    def test_delete_playlist(self, lib):
        p = lib.create_playlist("华语经典")
        lib.add_to_playlist(p.id, t(1))
        lib.delete_playlist(p.id)
        assert lib.playlists() == []

    def test_rename_playlist(self, lib):
        p = lib.create_playlist("旧名")
        lib.rename_playlist(p.id, "新名")
        assert lib.playlists()[0].name == "新名"

    def test_track_count_in_playlist_listing(self, lib):
        p = lib.create_playlist("华语经典")
        lib.add_to_playlist(p.id, t(1))
        lib.add_to_playlist(p.id, t(2))
        assert lib.playlists()[0].track_count == 2


class TestFavorites:
    def test_toggle_favorite(self, lib):
        assert lib.is_favorite(t(1).key) is False
        lib.toggle_favorite(t(1))
        assert lib.is_favorite(t(1).key) is True
        lib.toggle_favorite(t(1))
        assert lib.is_favorite(t(1).key) is False

    def test_favorites_listing(self, lib):
        lib.toggle_favorite(t(1))
        lib.toggle_favorite(t(2))
        assert {x.title for x in lib.favorites()} == {"歌曲1", "歌曲2"}


class TestHistory:
    def test_record_play_and_fetch(self, lib):
        lib.record_play(t(1), at=1000.0)
        lib.record_play(t(2), at=2000.0)
        rows = lib.history(limit=10)
        assert [r.track.title for r in rows] == ["歌曲2", "歌曲1"]  # newest first

    def test_history_keeps_repeat_plays(self, lib):
        lib.record_play(t(1), at=1000.0)
        lib.record_play(t(1), at=2000.0)
        assert len(lib.history(limit=10)) == 2

    def test_play_counts(self, lib):
        lib.record_play(t(1), at=1000.0)
        lib.record_play(t(1), at=2000.0)
        lib.record_play(t(2), at=3000.0)
        counts = lib.play_counts()
        assert counts[t(1).key] == 2
        assert counts[t(2).key] == 1

    def test_persistence_across_reopen(self, tmp_path):
        path = tmp_path / "yueting.db"
        lib1 = Library(path)
        p = lib1.create_playlist("华语经典")
        lib1.add_to_playlist(p.id, t(1))
        lib1.close()

        lib2 = Library(path)
        assert lib2.playlists()[0].name == "华语经典"
        assert lib2.playlist_tracks(lib2.playlists()[0].id)[0].title == "歌曲1"
        lib2.close()
