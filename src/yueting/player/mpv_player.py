r"""mpv 播放器控制：JSON IPC 协议，传输层可注入以便测试。

Windows 用命名管道 (\\.\pipe\yueting-mpv)，Linux/macOS 用 unix socket。
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import threading
import time
from typing import Protocol


class PlayerError(Exception):
    pass


def encode_request(command: list, request_id: int) -> bytes:
    return (json.dumps({"command": command, "request_id": request_id}, ensure_ascii=False) + "\n").encode("utf-8")


class Transport(Protocol):
    def send(self, payload: dict) -> dict: ...
    def close(self) -> None: ...


class PipeTransport:  # pragma: no cover - 集成层，需真实 mpv 进程
    """与真实 mpv 进程通信：启动 mpv --input-ipc-server 并同步收发 JSON 行。"""

    def __init__(self, mpv_path: str = "mpv", pipe_name: str | None = None) -> None:
        suffix = os.getpid()
        if sys.platform == "win32":
            self._ipc_path = pipe_name or f"\\\\.\\pipe\\yueting-mpv-{suffix}"
        else:
            self._ipc_path = pipe_name or f"/tmp/yueting-mpv-{suffix}.sock"
        self._proc = subprocess.Popen(
            [
                mpv_path,
                "--no-video",
                "--idle=yes",
                "--no-terminal",
                f"--input-ipc-server={self._ipc_path}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._handle = self._connect(timeout=10.0)
        self._request_id = 0
        self._lock = threading.Lock()  # UI 线程与后台线程可能同时发命令
        self._closed = False
        # TUI 无论正常退出、崩溃还是 Ctrl+C，都不能留下孤儿 mpv 进程
        atexit.register(self.close)

    def _connect(self, timeout: float):
        deadline = time.monotonic() + timeout
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise PlayerError("mpv 启动失败，请确认已安装 mpv 且在 PATH 中")
            try:
                if sys.platform == "win32":
                    return open(self._ipc_path, "r+b", buffering=0)
                import socket

                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(self._ipc_path)
                return sock
            except OSError as exc:
                last_err = exc
                time.sleep(0.1)
        raise PlayerError(f"连接 mpv IPC 超时：{last_err}")

    def send(self, payload: dict) -> dict:
        with self._lock:
            return self._send_locked(payload)

    def _send_locked(self, payload: dict) -> dict:
        self._request_id += 1
        request_id = self._request_id
        raw = encode_request(payload["command"], request_id)
        try:
            if sys.platform == "win32":
                self._handle.write(raw)
                while True:
                    line = self._readline()
                    reply = json.loads(line)
                    if reply.get("request_id") == request_id:
                        return reply
            else:
                self._handle.sendall(raw)
                buffer = b""
                while True:
                    buffer += self._handle.recv(4096)
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        reply = json.loads(line)
                        if reply.get("request_id") == request_id:
                            return reply
        except (OSError, ValueError) as exc:
            raise PlayerError(f"mpv 通信失败：{exc}") from exc

    def _readline(self) -> bytes:
        chunks = b""
        while not chunks.endswith(b"\n"):
            byte = self._handle.read(1)
            if not byte:
                raise PlayerError("mpv 管道已关闭")
            chunks += byte
        return chunks

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            with self._lock:
                self._handle.write(encode_request(["quit"], request_id=0))
        except Exception:
            pass
        try:
            self._handle.close()
        except OSError:
            pass
        if self._proc.poll() is None:
            try:
                self._proc.wait(timeout=2)  # 给 quit 命令一点时间优雅退出
            except subprocess.TimeoutExpired:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()


class MpvPlayer:
    """高层播放控制，业务代码只依赖这个接口。"""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _command(self, *command) -> dict:
        try:
            reply = self._transport.send({"command": list(command)})
        except Exception as exc:
            raise PlayerError(f"播放器命令失败：{exc}") from exc
        return reply

    def _get_property(self, name: str):
        reply = self._command("get_property", name)
        if reply.get("error") != "success":
            return None
        return reply.get("data")

    def play(self, url: str, title: str = "", headers: dict[str, str] | None = None) -> None:
        headers = dict(headers or {})
        user_agent = headers.pop("User-Agent", None)
        # 请求头必须在 loadfile 之前设置；不带头的曲目要清掉上一首的
        self._command(
            "set_property",
            "http-header-fields",
            [f"{k}: {v}" for k, v in headers.items()],
        )
        if user_agent:
            self._command("set_property", "user-agent", user_agent)
        self._command("loadfile", url, "replace")
        if title:
            self._command("set_property", "force-media-title", title)
        self._command("set_property", "pause", False)

    def toggle_pause(self) -> None:
        self._command("cycle", "pause")

    def stop(self) -> None:
        self._command("stop")

    def seek(self, seconds: float) -> None:
        self._command("seek", seconds, "relative")

    def set_volume(self, volume: float) -> None:
        clamped = max(0, min(100, volume))
        self._command("set_property", "volume", clamped)

    def position(self) -> float | None:
        return self._get_property("time-pos")

    def duration(self) -> float | None:
        return self._get_property("duration")

    def is_paused(self) -> bool | None:
        return self._get_property("pause")

    def volume(self) -> float | None:
        return self._get_property("volume")

    def is_idle(self) -> bool | None:
        return self._get_property("idle-active")

    def close(self) -> None:
        self._transport.close()
