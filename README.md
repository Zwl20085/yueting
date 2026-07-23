# 悦听 (YueTing) 🎵

中文向终端音乐播放器（TUI）。从 **B站** 和 **YouTube** 搜歌、建歌单、听推荐，全部在终端里完成。

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Tests](https://img.shields.io/badge/tests-118%20passed-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

## 功能

- 🔍 **多源搜索** — 通过 yt-dlp 搜索 Bilibili（`s` 键切换 YouTube）
- 📂 **歌单管理** — 新建歌单、添加/移除歌曲、收藏，本地 SQLite 持久化
- 🎯 **本地推荐** — 不依赖 LLM / 云端：标题字符 bigram 相似度 + 同会话共现 + 热度加权
- 🪟 **迷你模式** — 按 `m` 收起界面，只留一行播放条（⏮ ⏯ ⏭ + 进度）
- 🔁 **播放模式** — 顺序 / 列表循环 / 单曲循环 / 随机
- ⚡ **快** — B站搜索走官方 API（约 1–2 秒返回 20 条），yt-dlp 自动兜底；
  下一首流地址后台预取，切歌接近零等待；搜索结果与流地址均有本地缓存
- 🧪 **TDD 开发** — 118 个测试，核心逻辑覆盖率 97%

## 安装

前置依赖：[mpv](https://mpv.io)（播放引擎）

```powershell
# Windows
winget install shinchiro.mpv
# macOS: brew install mpv    Linux: apt install mpv
```

安装运行：

```powershell
git clone https://github.com/Zwl20085/yueting.git
cd yueting
uv sync
uv run yueting
```

## 快捷键

| 键 | 功能 | 键 | 功能 |
|----|------|----|------|
| `/` | 聚焦搜索框 | `空格` | 播放/暂停 |
| `回车` | 搜索 / 播放选中曲目 | `n` / `p` | 下一首 / 上一首 |
| `s` | 切换音乐源（B站/油管） | `←` / `→` | 快退 / 快进 5 秒 |
| `f` | 收藏当前/选中歌曲 | `-` / `=` | 音量减 / 加 |
| `a` | 添加到歌单 | `r` | 切换播放模式 |
| `Ctrl+N` | 新建歌单 | `m` | **迷你模式** |
| `g` | ✨ 猜你想听（推荐） | `q` | 退出 |

## 架构

```
src/yueting/
├── models.py          # 领域模型（不可变 dataclass）
├── controller.py      # 播放控制器：UI 只与它交互
├── sources/
│   ├── bilibili_api.py# B站官方搜索 API（~1s，主路径）
│   └── ytdlp_source.py# yt-dlp 搜索/取流（油管 + B站兜底），带缓存
├── player/
│   ├── queue.py       # 播放队列：纯函数 + 不可变状态
│   └── mpv_player.py  # mpv JSON IPC（传输层可注入，便于测试）
├── store/library.py   # SQLite 曲库（歌单/收藏/历史，Repository 模式）
├── recommend/engine.py# 本地推荐引擎（无 LLM）
└── ui/                # Textual TUI
```

推荐算法：`score = 内容相似度(标题bigram Jaccard + UP主加成) + 0.5 × 会话共现 + 0.05 × 热度`，
自动排除最近听过的 20 首，冷启动时直接返回候选。

## 开发

```powershell
uv run pytest                 # 全部测试
uv run pytest --cov           # 含覆盖率
```

测试全程无网络、无 mpv 依赖：yt-dlp 用 mock、播放器用注入的假传输层。

## 免责声明

本项目仅供个人学习与技术研究。音频流均来自公开平台的临时链接，不缓存、不下载、不分发。请支持正版音乐。

## License

MIT
