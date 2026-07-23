"""Tests for the non-LLM recommendation engine.

策略：共现 (同会话播放) + 内容相似 (标题字符 bigram / UP主) + 热度，纯本地计算。
"""
from yueting.models import Source, Track
from yueting.recommend.engine import PlayEvent, recommend, similarity


def t(n: int, title: str, uploader: str = "up", source: Source = Source.BILIBILI) -> Track:
    return Track(
        id=f"id{n}",
        source=source,
        title=title,
        uploader=uploader,
        duration=100.0,
        webpage_url=f"https://example.com/{n}",
    )


JAY1 = t(1, "周杰伦 - 晴天", uploader="杰威尔音乐")
JAY2 = t(2, "周杰伦 - 七里香", uploader="杰威尔音乐")
JAY3 = t(3, "周杰伦 - 稻香", uploader="杰威尔音乐")
ROCK = t(4, "Beyond - 海阔天空", uploader="环球音乐")
LOFI = t(5, "lofi hip hop radio", uploader="Lofi Girl", source=Source.YOUTUBE)


class TestSimilarity:
    def test_same_artist_prefix_titles_are_similar(self):
        assert similarity(JAY1, JAY2) > similarity(JAY1, ROCK)

    def test_same_uploader_boosts(self):
        a = t(10, "曲A", uploader="同一个UP")
        b = t(11, "曲B", uploader="同一个UP")
        c = t(12, "曲C", uploader="别的UP")
        assert similarity(a, b) > similarity(a, c)

    def test_similarity_symmetric(self):
        assert similarity(JAY1, ROCK) == similarity(ROCK, JAY1)

    def test_self_similarity_is_max(self):
        assert similarity(JAY1, JAY1) >= similarity(JAY1, JAY2)


class TestRecommend:
    def make_history(self):
        # 两个收听会话：会话1 常一起听周杰伦，会话2 听摇滚
        return [
            PlayEvent(track=JAY1, at=1000.0),
            PlayEvent(track=JAY2, at=1200.0),
            PlayEvent(track=JAY1, at=5000.0),
            PlayEvent(track=JAY2, at=5200.0),
            PlayEvent(track=ROCK, at=99000.0),
        ]

    def test_excludes_recently_played_seed(self):
        recs = recommend(self.make_history(), candidates=[JAY1, JAY2, JAY3, LOFI], limit=5)
        keys = [r.key for r in recs]
        assert JAY1.key not in keys  # 不推荐刚听过的
        assert JAY2.key not in keys

    def test_recommends_similar_unheard_track_first(self):
        recs = recommend(self.make_history(), candidates=[JAY3, LOFI], limit=2)
        assert recs[0].key == JAY3.key  # 稻香和听过的周杰伦最像

    def test_respects_limit(self):
        recs = recommend(self.make_history(), candidates=[JAY3, LOFI, ROCK], limit=1)
        assert len(recs) == 1

    def test_empty_history_returns_candidates_unranked_but_capped(self):
        recs = recommend([], candidates=[JAY1, ROCK], limit=1)
        assert len(recs) == 1

    def test_empty_candidates(self):
        assert recommend(self.make_history(), candidates=[], limit=5) == []

    def test_cooccurrence_influences_ranking(self):
        # LOFI 和 JAY1 虽然内容不像，但历史上总在同一会话出现 → 应排在 ROCK 前
        history = [
            PlayEvent(track=JAY1, at=1000.0),
            PlayEvent(track=LOFI, at=1100.0),
            PlayEvent(track=JAY1, at=2000.0),
            PlayEvent(track=LOFI, at=2100.0),
            PlayEvent(track=JAY1, at=3000.0),
        ]
        candidates = [LOFI, ROCK]
        # LOFI 最近听过，先把"最近"窗口缩小到只排除 JAY1
        recs = recommend(history, candidates=candidates, limit=2, recent_exclude=1)
        assert recs[0].key == LOFI.key
