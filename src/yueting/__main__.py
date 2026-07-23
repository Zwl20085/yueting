"""程序入口：`yueting` 或 `python -m yueting`。"""
from __future__ import annotations

import sys

from yueting import config
from yueting.controller import PlayerController
from yueting.player.mpv_player import MpvPlayer, PipeTransport, PlayerError
from yueting.sources.ytdlp_source import YtdlpSource
from yueting.store.library import Library
from yueting.ui.app import YueTingApp


def main() -> int:
    mpv_path = config.find_mpv()
    if mpv_path is None:
        print("未找到 mpv。请先安装：winget install shinchiro.mpv", file=sys.stderr)
        return 1
    try:
        transport = PipeTransport(mpv_path=mpv_path)
    except PlayerError as exc:
        print(f"启动 mpv 失败：{exc}", file=sys.stderr)
        return 1

    controller = PlayerController(
        player=MpvPlayer(transport=transport),
        source=YtdlpSource(),
        library=Library(config.db_path()),
    )
    try:
        YueTingApp(controller).run()
    finally:
        try:
            controller.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
