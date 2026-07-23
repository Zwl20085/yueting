"""UI 冒烟测试：Textual pilot 驱动，播放器与音乐源全部为假实现。"""
import pytest

from yueting.controller import PlayerController
from yueting.models import Source, Track
from yueting.store.library import Library
from yueting.ui.app import YueTingApp


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
    def play(self, url, title=""): ...
    def toggle_pause(self): ...
    def stop(self): ...
    def seek(self, s): ...
    def set_volume(self, v): ...
    def position(self): return 10.0
    def duration(self): return 100.0
    def is_paused(self): return False
    def volume(self): return 80.0
    def is_idle(self): return False
    def close(self): ...


class FakeSource:
    def search(self, query, source, limit=10):
        return [t(1), t(2)]

    def resolve_stream_url(self, webpage_url):
        return f"stream://{webpage_url}"


@pytest.fixture
def app(tmp_path):
    controller = PlayerController(
        player=FakePlayer(), source=FakeSource(), library=Library(tmp_path / "db.sqlite")
    )
    return YueTingApp(controller)


async def test_app_mounts_and_shows_player_bar(app):
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one("#player-bar")
        assert "未在播放" in str(bar.render())


async def test_search_flow_populates_table(app):
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.click("#search-input")
        await pilot.press(*"tian")
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert len(app.shown_tracks) == 2


async def test_mini_mode_toggle(app):
    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one("#results").focus()
        await pilot.press("m")
        assert app.has_class("mini")
        await pilot.press("m")
        assert not app.has_class("mini")


async def test_switch_source(app):
    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one("#results").focus()
        assert app.search_source is Source.BILIBILI
        await pilot.press("s")
        assert app.search_source is Source.YOUTUBE
