from datetime import date, datetime

from app.config import IST
from app.nodes.filter_rank import filter_rank, parse_date
from app.schemas import RawArticle

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=IST)


def raw(title, d, url=None, score=0.5):
    return RawArticle(
        title=title,
        url=url or f"https://www.site.com/{title.replace(' ', '-')}",
        content="c",
        published_date=d,
        score=score,
    )


def titles(result):
    return [a.title for a in result]


def test_drops_old_undated_future_and_unparseable():
    items = [
        raw("today", "2026-10-29"),
        raw("old", "2026-09-19"),  # 40 days
        raw("none", None),
        raw("future", "2026-11-05"),
        raw("garbage", "not a date"),
    ]
    assert titles(filter_rank(items, now=NOW)) == ["today"]


def test_30_day_boundary():
    items = [raw("edge", "2026-09-29"), raw("over", "2026-09-28")]
    assert titles(filter_rank(items, now=NOW)) == ["edge"]


def test_ranking_recent_first_then_newest_then_score():
    items = [
        raw("ten days", "2026-10-19", score=0.9),
        raw("yesterday", "2026-10-28", score=0.1),
        raw("today low", "2026-10-29", score=0.2),
        raw("today high", "2026-10-29", score=0.8),
        raw("five days", "2026-10-24", score=0.5),
    ]
    assert titles(filter_rank(items, now=NOW)) == [
        "today high", "today low", "yesterday", "five days", "ten days",
    ]


def test_recent_flag():
    result = filter_rank(
        [raw("a", "2026-10-28"), raw("b", "2026-10-27")], now=NOW
    )
    flags = {a.title: a.is_today_or_yesterday for a in result}
    assert flags == {"a": True, "b": False}


def test_dedupes_by_url_and_title():
    items = [
        raw("same url", "2026-10-29", url="https://x.com/a"),
        raw("other title", "2026-10-29", url="https://x.com/a/"),
        raw("Same Title", "2026-10-28", url="https://x.com/b"),
        raw("same title", "2026-10-28", url="https://x.com/c"),
    ]
    assert len(filter_rank(items, now=NOW)) == 2


def test_max_articles_and_ids():
    items = [raw(f"n{i}", "2026-10-29", score=i / 20) for i in range(12)]
    result = filter_rank(items, max_articles=8, now=NOW)
    assert len(result) == 8
    assert [a.id for a in result] == list(range(1, 9))


def test_source_strips_www():
    result = filter_rank([raw("a", "2026-10-29", url="https://www.site.com/x")], now=NOW)
    assert result[0].source == "site.com"


def test_parse_date_formats():
    assert parse_date("2026-10-28") == date(2026, 10, 28)
    assert parse_date("2026-10-28T10:00:00Z") == date(2026, 10, 28)
    assert parse_date("Wed, 28 Oct 2026 10:00:00 GMT") == date(2026, 10, 28)


def test_parse_date_converts_to_ist():
    # 20:00 UTC on the 28th is 01:30 IST on the 29th
    assert parse_date("2026-10-28T20:00:00Z") == date(2026, 10, 29)
