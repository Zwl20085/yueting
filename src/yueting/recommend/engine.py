"""本地推荐引擎（不依赖 LLM / 云端）。

评分 = 内容相似度（标题字符 bigram Jaccard + UP主加成）
     + 会话共现（和听过的歌出现在同一收听会话）
     + 轻微热度项。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from yueting.models import Track

SESSION_GAP_SECONDS = 30 * 60  # 间隔超过30分钟视为新的收听会话
_UPLOADER_BONUS = 0.3
_COOCCURRENCE_WEIGHT = 0.5
_POPULARITY_WEIGHT = 0.05
_DEFAULT_RECENT_EXCLUDE = 20


@dataclass(frozen=True, slots=True)
class PlayEvent:
    track: Track
    at: float


def _bigrams(text: str) -> set[str]:
    cleaned = "".join(ch.lower() for ch in text if not ch.isspace())
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def similarity(a: Track, b: Track) -> float:
    """内容相似度 ∈ [0, 1+bonus]：标题 bigram Jaccard，同 UP主 加成。"""
    ga, gb = _bigrams(a.title), _bigrams(b.title)
    union = ga | gb
    jaccard = len(ga & gb) / len(union) if union else 0.0
    bonus = _UPLOADER_BONUS if a.uploader and a.uploader == b.uploader else 0.0
    return jaccard + bonus


def _split_sessions(history: list[PlayEvent]) -> list[list[PlayEvent]]:
    ordered = sorted(history, key=lambda e: e.at)
    sessions: list[list[PlayEvent]] = []
    for event in ordered:
        if sessions and event.at - sessions[-1][-1].at <= SESSION_GAP_SECONDS:
            sessions[-1].append(event)
        else:
            sessions.append([event])
    return sessions


def _cooccurrence_counts(history: list[PlayEvent]) -> Counter[frozenset[str]]:
    counts: Counter[frozenset[str]] = Counter()
    for session in _split_sessions(history):
        keys = {e.track.key for e in session}
        for a in keys:
            for b in keys:
                if a < b:
                    counts[frozenset((a, b))] += 1
    return counts


def recommend(
    history: list[PlayEvent],
    candidates: list[Track],
    limit: int = 10,
    recent_exclude: int = _DEFAULT_RECENT_EXCLUDE,
) -> list[Track]:
    """从候选中挑出最值得听的曲目，排除最近刚听过的。"""
    if not candidates:
        return []
    if not history:
        return list(candidates)[:limit]

    ordered = sorted(history, key=lambda e: e.at, reverse=True)
    recent_keys = []
    for event in ordered:
        if event.track.key not in recent_keys:
            recent_keys.append(event.track.key)
        if len(recent_keys) >= recent_exclude:
            break
    excluded = set(recent_keys)

    play_counts = Counter(e.track.key for e in history)
    profile: dict[str, Track] = {e.track.key: e.track for e in history}
    cooc = _cooccurrence_counts(history)
    max_cooc = max(cooc.values(), default=1)

    def score(candidate: Track) -> float:
        content = max(
            (similarity(candidate, heard) for heard in profile.values()), default=0.0
        )
        cooc_score = max(
            (
                cooc.get(frozenset((candidate.key, heard_key)), 0) / max_cooc
                for heard_key in profile
                if heard_key != candidate.key
            ),
            default=0.0,
        )
        popularity = play_counts.get(candidate.key, 0) / max(play_counts.values())
        return content + _COOCCURRENCE_WEIGHT * cooc_score + _POPULARITY_WEIGHT * popularity

    ranked = sorted(
        (c for c in candidates if c.key not in excluded), key=score, reverse=True
    )
    return ranked[:limit]
