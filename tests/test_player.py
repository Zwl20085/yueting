"""Tests for the mpv IPC player — transport is injected, no real mpv needed."""
import json

import pytest

from yueting.player.mpv_player import MpvPlayer, PlayerError


class FakeTransport:
    """Records commands; replies with success and canned property values."""

    def __init__(self):
        self.sent: list[dict] = []
        self.properties = {"time-pos": 42.5, "duration": 269.0, "pause": False, "volume": 80.0}
        self.connected = True

    def send(self, payload: dict) -> dict:
        self.sent.append(payload)
        cmd = payload["command"]
        if cmd[0] == "get_property":
            name = cmd[1]
            if name not in self.properties:
                return {"error": "property unavailable"}
            return {"error": "success", "data": self.properties[name]}
        return {"error": "success"}

    def close(self):
        self.connected = False


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def player(transport):
    return MpvPlayer(transport=transport)


class TestCommands:
    def test_play_sends_loadfile(self, player, transport):
        player.play("https://cdn.example.com/a.m4a", title="晴天")
        cmds = [p["command"] for p in transport.sent]
        assert ["loadfile", "https://cdn.example.com/a.m4a", "replace"] in cmds
        # 播放新曲目时必须取消暂停
        assert ["set_property", "pause", False] in cmds

    def test_toggle_pause(self, player, transport):
        player.toggle_pause()
        assert ["cycle", "pause"] in [p["command"] for p in transport.sent]

    def test_stop(self, player, transport):
        player.stop()
        assert ["stop"] in [p["command"] for p in transport.sent]

    def test_seek_relative(self, player, transport):
        player.seek(10)
        assert ["seek", 10, "relative"] in [p["command"] for p in transport.sent]

    def test_set_volume_clamps_to_0_100(self, player, transport):
        player.set_volume(150)
        assert ["set_property", "volume", 100] in [p["command"] for p in transport.sent]
        player.set_volume(-5)
        assert ["set_property", "volume", 0] in [p["command"] for p in transport.sent]


class TestProperties:
    def test_position_and_duration(self, player):
        assert player.position() == 42.5
        assert player.duration() == 269.0

    def test_is_paused(self, player):
        assert player.is_paused() is False

    def test_missing_property_returns_none(self, player, transport):
        del transport.properties["time-pos"]
        assert player.position() is None


class TestErrors:
    def test_command_error_raises_player_error(self, player, transport):
        def bad_send(payload):
            raise ConnectionError("pipe broken")

        transport.send = bad_send
        with pytest.raises(PlayerError):
            player.toggle_pause()

    def test_close_closes_transport(self, player, transport):
        player.close()
        assert transport.connected is False


class TestIpcEncoding:
    def test_request_is_json_line(self):
        """协议层：每条命令是一行 JSON + newline (mpv JSON IPC)。"""
        from yueting.player.mpv_player import encode_request

        raw = encode_request(["get_property", "time-pos"], request_id=7)
        line = raw.decode("utf-8")
        assert line.endswith("\n")
        obj = json.loads(line)
        assert obj == {"command": ["get_property", "time-pos"], "request_id": 7}
