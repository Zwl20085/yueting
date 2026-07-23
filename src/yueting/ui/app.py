"""悦听 TUI 主界面 (Textual)。"""
from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Input, Label, ListItem, ListView, Static

from yueting.controller import PlayerController
from yueting.models import Source, Track
from yueting.recommend.engine import PlayEvent, recommend
from yueting.sources.ytdlp_source import SearchError
from yueting.ui.modals import NewPlaylistModal, PickPlaylistModal

_SIDEBAR_FAVORITES = "sidebar-favorites"
_SIDEBAR_PREFIX = "sidebar-pl-"


class YueTingApp(App):
    """主应用：搜索 → 结果表 → 播放；歌单侧栏；迷你模式。"""

    TITLE = "悦听"
    CSS = """
    #search-row { height: 3; }
    #search-input { width: 1fr; }
    #source-label { width: auto; padding: 1 2; color: $accent; }
    #body { height: 1fr; }
    #sidebar { width: 26; border-right: solid $primary; }
    #sidebar-title { padding: 0 1; color: $text-muted; }
    #results { width: 1fr; }
    #player-bar {
        dock: bottom; height: 3; padding: 0 1;
        background: $surface; border-top: solid $primary;
    }
    #modal-box {
        width: 60; height: auto; max-height: 20; padding: 1 2;
        background: $surface; border: thick $primary;
        align: center middle;
    }
    NewPlaylistModal, PickPlaylistModal { align: center middle; }
    .mini #search-row, .mini #body, .mini Footer { display: none; }
    """

    BINDINGS = [
        Binding("slash", "focus_search", "搜索", key_display="/"),
        Binding("space", "toggle_pause", "播放/暂停"),
        Binding("n", "next_track", "下一首"),
        Binding("p", "prev_track", "上一首"),
        Binding("m", "toggle_mini", "迷你模式"),
        Binding("r", "cycle_mode", "播放模式"),
        Binding("f", "favorite", "收藏"),
        Binding("a", "add_to_playlist", "加入歌单"),
        Binding("ctrl+n", "new_playlist", "新建歌单"),
        Binding("g", "show_recommendations", "推荐"),
        Binding("s", "switch_source", "切换音乐源"),
        Binding("left", "seek(-5)", "快退", show=False),
        Binding("right", "seek(5)", "快进", show=False),
        Binding("minus", "volume(-5)", "音量-", show=False),
        Binding("equals_sign", "volume(5)", "音量+", show=False),
        Binding("q", "quit", "退出"),
    ]

    def __init__(self, controller: PlayerController) -> None:
        super().__init__()
        self.controller = controller
        self.controller.on_error = lambda msg: self.call_from_thread(self._notify_error, msg)
        self.search_source = Source.BILIBILI
        self.shown_tracks: list[Track] = []
        self.mini_mode = False

    # -- layout -------------------------------------------------------------
    def compose(self) -> ComposeResult:
        with Horizontal(id="search-row"):
            yield Input(placeholder="搜索歌曲 / 歌手…（回车搜索）", id="search-input")
            yield Label(self.search_source.display, id="source-label")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("我的歌单（回车打开）", id="sidebar-title")
                yield ListView(id="playlist-list")
            yield DataTable(id="results", cursor_type="row")
        yield Static("♪ 未在播放", id="player-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results", DataTable)
        table.add_columns("标题", "UP主/频道", "时长", "来源")
        self._refresh_sidebar()
        self.set_interval(1.0, self._tick)
        self.query_one("#search-input", Input).focus()

    # -- helpers --------------------------------------------------------------
    def _notify_error(self, message: str) -> None:
        self.notify(message, severity="error", timeout=6)

    def _refresh_sidebar(self) -> None:
        listing = self.query_one("#playlist-list", ListView)
        listing.clear()
        listing.append(ListItem(Label("❤ 我的收藏"), id=_SIDEBAR_FAVORITES))
        for playlist in self.controller.library.playlists():
            listing.append(
                ListItem(
                    Label(f"♪ {playlist.name}（{playlist.track_count}）"),
                    id=f"{_SIDEBAR_PREFIX}{playlist.id}",
                )
            )

    def _show_tracks(self, tracks: list[Track], context: str) -> None:
        self.shown_tracks = list(tracks)
        table = self.query_one("#results", DataTable)
        table.clear()
        for track in tracks:
            table.add_row(track.title, track.uploader, track.duration_display, track.source.display)
        self.sub_title = context
        if tracks:
            table.focus()

    def _selected_track(self) -> Track | None:
        table = self.query_one("#results", DataTable)
        if not self.shown_tracks or table.cursor_row is None:
            return None
        if 0 <= table.cursor_row < len(self.shown_tracks):
            return self.shown_tracks[table.cursor_row]
        return None

    def _tick(self) -> None:
        track = self.controller.current
        bar = self.query_one("#player-bar", Static)
        if track is None:
            bar.update("♪ 未在播放 — 按 / 搜索，回车播放")
            return
        pos = self.controller.player.position() or 0.0
        dur = self.controller.player.duration() or track.duration or 0.0
        paused = self.controller.player.is_paused()
        icon = "⏸" if paused else "▶"
        ratio = min(pos / dur, 1.0) if dur else 0.0
        width = 20
        fill = int(ratio * width)
        gauge = "▓" * fill + "░" * (width - fill)

        def fmt(seconds: float) -> str:
            minutes, secs = divmod(int(seconds), 60)
            return f"{minutes:02d}:{secs:02d}"

        mode = self.controller.queue.mode.display
        bar.update(
            f"{icon} {track.title} — {track.uploader}  {fmt(pos)}/{fmt(dur)} {gauge}  [{mode}]"
        )
        # 播放结束自动切歌：位置停在结尾且播放器空闲
        if dur and pos >= dur - 0.5 and not paused:
            idle = getattr(self.controller.player, "is_idle", lambda: None)()
            if idle:
                self._advance_auto()

    @work(thread=True, exclusive=True, group="playback")
    def _advance_auto(self) -> None:
        self.controller.next(manual=False)

    # -- search ---------------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input" and event.value.strip():
            self.sub_title = f"正在搜索「{event.value}」…"
            self._do_search(event.value.strip())

    @work(thread=True, exclusive=True, group="search")
    def _do_search(self, query: str) -> None:
        try:
            tracks = self.controller.source.search(query, self.search_source, limit=10)
        except (SearchError, ValueError) as exc:
            self.call_from_thread(self._notify_error, str(exc))
            return
        label = f"{self.search_source.display}搜索：{query}（{len(tracks)}个结果）"
        self.call_from_thread(self._show_tracks, tracks, label)

    # -- table & sidebar interaction ----------------------------------------
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self.shown_tracks:
            self._play_from(event.cursor_row)

    @work(thread=True, exclusive=True, group="playback")
    def _play_from(self, index: int) -> None:
        self.controller.play_now(self.shown_tracks, start=index)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if item_id == _SIDEBAR_FAVORITES:
            self._show_tracks(self.controller.library.favorites(), "❤ 我的收藏")
        elif item_id.startswith(_SIDEBAR_PREFIX):
            playlist_id = int(item_id.removeprefix(_SIDEBAR_PREFIX))
            names = {p.id: p.name for p in self.controller.library.playlists()}
            tracks = self.controller.library.playlist_tracks(playlist_id)
            self._show_tracks(tracks, f"歌单：{names.get(playlist_id, '')}")

    # -- actions ---------------------------------------------------------------
    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    def action_toggle_pause(self) -> None:
        self.controller.toggle_pause()

    @work(thread=True, exclusive=True, group="playback")
    def action_next_track(self) -> None:
        self.controller.next()

    @work(thread=True, exclusive=True, group="playback")
    def action_prev_track(self) -> None:
        self.controller.prev()

    def action_toggle_mini(self) -> None:
        self.mini_mode = not self.mini_mode
        self.set_class(self.mini_mode, "mini")

    def action_cycle_mode(self) -> None:
        self.controller.cycle_mode()
        self.notify(f"播放模式：{self.controller.queue.mode.display}", timeout=2)

    def action_switch_source(self) -> None:
        self.search_source = (
            Source.YOUTUBE if self.search_source is Source.BILIBILI else Source.BILIBILI
        )
        self.query_one("#source-label", Label).update(self.search_source.display)
        self.notify(f"音乐源：{self.search_source.display}", timeout=2)

    def action_seek(self, seconds: float) -> None:
        self.controller.seek(seconds)

    def action_volume(self, delta: float) -> None:
        current = self.controller.player.volume() or 80.0
        self.controller.set_volume(current + delta)

    def action_favorite(self) -> None:
        track = self._selected_track() or self.controller.current
        if track is None:
            self.notify("没有可收藏的歌曲", severity="warning", timeout=3)
            return
        now_fav = self.controller.library.toggle_favorite(track)
        self.notify(f"{'❤ 已收藏' if now_fav else '已取消收藏'}：{track.title}", timeout=3)
        self._refresh_sidebar()

    def action_new_playlist(self) -> None:
        def on_result(name: str | None) -> None:
            if not name:
                return
            try:
                self.controller.library.create_playlist(name)
            except ValueError as exc:
                self._notify_error(str(exc))
                return
            self._refresh_sidebar()
            self.notify(f"已创建歌单「{name}」", timeout=3)

        self.push_screen(NewPlaylistModal(), on_result)

    def action_add_to_playlist(self) -> None:
        track = self._selected_track() or self.controller.current
        if track is None:
            self.notify("先选中一首歌", severity="warning", timeout=3)
            return
        playlists = self.controller.library.playlists()
        if not playlists:
            self.notify("还没有歌单，按 Ctrl+N 新建", severity="warning", timeout=4)
            return

        def on_result(playlist_id: int | None) -> None:
            if playlist_id is None:
                return
            self.controller.library.add_to_playlist(playlist_id, track)
            self._refresh_sidebar()
            self.notify(f"已添加「{track.title}」", timeout=3)

        self.push_screen(PickPlaylistModal(playlists), on_result)

    def action_show_recommendations(self) -> None:
        history = [
            PlayEvent(track=h.track, at=h.played_at)
            for h in self.controller.library.history(limit=500)
        ]
        seen = {e.track.key: e.track for e in history}
        candidates = [
            t for t in (
                self.controller.library.favorites()
                + [p for pl in self.controller.library.playlists()
                   for p in self.controller.library.playlist_tracks(pl.id)]
                + list(seen.values())
            )
        ]
        # 去重
        unique: dict[str, Track] = {}
        for t in candidates:
            unique.setdefault(t.key, t)
        recs = recommend(history, list(unique.values()), limit=20)
        if not recs:
            self.notify("听几首歌之后再来看推荐吧～", timeout=4)
            return
        self._show_tracks(recs, "✨ 猜你想听（本地推荐）")

    def action_quit(self) -> None:
        self.controller.close()
        self.exit()
