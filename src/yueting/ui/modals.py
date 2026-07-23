"""弹窗：新建歌单、选择歌单。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView

from yueting.models import Playlist


class NewPlaylistModal(ModalScreen[str | None]):
    """输入新歌单名称；ESC 取消。"""

    BINDINGS = [("escape", "cancel", "取消")]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Label("新建歌单（回车确认，ESC 取消）")
            yield Input(placeholder="歌单名称…", id="playlist-name")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        self.dismiss(name or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PickPlaylistModal(ModalScreen[int | None]):
    """从现有歌单中选择一个，返回歌单 id。"""

    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, playlists: list[Playlist]) -> None:
        super().__init__()
        self._playlists = playlists

    def compose(self) -> ComposeResult:
        items = [
            ListItem(Label(f"{p.name}（{p.track_count}首）"), id=f"pl-{p.id}")
            for p in self._playlists
        ]
        with Vertical(id="modal-box"):
            yield Label("添加到哪个歌单？（回车确认，ESC 取消）")
            yield ListView(*items)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        raw = (event.item.id or "").removeprefix("pl-")
        self.dismiss(int(raw) if raw.isdigit() else None)

    def action_cancel(self) -> None:
        self.dismiss(None)
