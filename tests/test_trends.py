from datetime import date, timedelta

from app.db import list_impacts, save_run
from app.schemas import Article, CardOut
from app.trends import build_trends, score

TODAY = date(2026, 11, 2)


def row(days_ago, sentiment, title="Coal prices rise", summary="s"):
    return {"title": title, "url": f"https://s.com/{title}/{days_ago}", "source": "s.com",
            "published_date": (TODAY - timedelta(days=days_ago)).isoformat(),
            "summary": summary, "sentiment": sentiment, "level": "high", "horizon": "short"}


def test_score_range():
    assert score([]) is None
    assert score([row(1, "positive")]) == 100
    assert score([row(1, "negative"), row(1, "positive"), row(1, "neutral"), row(1, "negative")]) == -25


def test_coal_turning_negative_is_highlighted():
    rows = [row(25, "positive"), row(20, "positive"), row(5, "negative"), row(1, "negative")]
    t = build_trends(rows, 30, TODAY)
    coal = next(x for x in t["themes"] if x["theme"] == "Coal")
    assert (coal["earlier_score"], coal["recent_score"], coal["direction"]) == (100, -100, "worse")
    assert t["highlights"][0] == "Coal news is turning more negative (+100 → -100)"
    assert t["overall"]["score"] == 0 and t["total"] == 4


def test_daily_covers_every_day_and_old_news_is_ignored():
    t = build_trends([row(0, "positive"), row(40, "negative")], 7, TODAY)
    assert len(t["daily"]) == 7
    assert t["daily"][-1] == {"date": "2026-11-02", "positive": 1, "negative": 0, "neutral": 0}
    assert t["total"] == 1


def test_theme_only_in_recent_half_is_new_and_small_changes_are_steady():
    t = build_trends([row(1, "positive", title="New ALMM policy")], 30, TODAY)
    assert t["themes"][0]["theme"] == "Policy" and t["themes"][0]["direction"] == "new"
    t = build_trends([row(25, "positive"), row(2, "positive")], 30, TODAY)
    assert t["themes"][0]["direction"] == "steady"


def test_list_impacts_keeps_newest_analysis_per_url(tmp_path):
    db = str(tmp_path / "t.db")
    art = Article(id=1, title="Coal up", url="https://s.com/1", source="s.com",
                  published_date="2026-10-30", content="c", is_today_or_yesterday=False)

    def run(sentiment):
        card = CardOut(article_id=1, relevant=True, summary="s", sentiment=sentiment, level="high",
                       reason="r", horizon="short", title="Coal up", url="https://s.com/1",
                       source="s.com", published_date="2026-10-30")
        return {"status": "ok", "message": None, "summary": [], "cards": [card], "articles": [art]}

    save_run("q", None, run("positive"), path=db)
    save_run("q", None, run("negative"), path=db)
    rows = list_impacts("2026-10-01", path=db)
    assert len(rows) == 1 and rows[0]["sentiment"] == "negative"
    assert list_impacts("2026-10-31", path=db) == []
