"""运行配置：数据目录与 mpv 路径探测。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_NAME = "yueting"

# Windows 上 winget 安装 mpv 后可能不在当前会话 PATH 中的备选位置
_WINDOWS_MPV_CANDIDATES = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "mpv.exe",
    Path("C:/Program Files/MPV Player/mpv.exe"),  # winget shinchiro.mpv 默认位置
    Path("C:/Program Files/mpv/mpv.exe"),
)


def data_dir() -> Path:
    root = Path(os.environ.get("YUETING_HOME", Path.home() / ".yueting"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def db_path() -> Path:
    return data_dir() / "library.db"


def find_mpv() -> str | None:
    found = shutil.which("mpv")
    if found:
        return found
    for candidate in _WINDOWS_MPV_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    return None
