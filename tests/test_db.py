import sqlite3

import pytest

from app.db import get_run, init_db, list_runs, save_run
from app.schemas import Article, CardOut, SummaryOut


def article(i):
    return Article(
        id=i, title=f"title {i}", url=f"https://s.com/{i}", source="s.com",
        published_date="2026-10-29", content=f"body {i}", is_today_or_yesterday=True,
    )


def card(i, **kw):
    base = dict(
        article_id=i, relevant=True, summary=f"s{i}", sentiment="negative", level="high",
        reason=f"r{i}", horizon="short", title=f"title {i}", url=f"https://s.com/{i}",
        source="s.com", published_date="2026-10-29",
    )
    return CardOut(**{**base, **kw})


def ok_result():
    return {
        "status": "ok",
        "message": None,
        "summary": [SummaryOut(text="point", sources=["https://s.com/1", "https://s.com/2"])],
        "cards": [card(1), card(2)],
        "articles": [article(1), article(2), article(3)],
    }


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "test.db")


def test_init_twice_is_safe(db):
    init_db(db)
    init_db(db)
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"queries", "articles", "impacts"} <= tables


def test_save_then_get_roundtrip(db):
    qid = save_run("my question", "policy", ok_result(), path=db)
    run = get_run(qid, path=db)
    assert run.query_id == qid and run.status == "ok" and run.message is None
    assert run.summary == ok_result()["summary"]
    assert run.cards == ok_result()["cards"]


def test_only_validated_cards_get_impacts_but_all_articles_saved(db):
    qid = save_run("q", None, ok_result(), path=db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM articles WHERE query_id=?", (qid,)).fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM impacts").fetchone()[0] == 2


def test_no_news_and_error_runs_are_saved(db):
    empty = {"status": "no_news", "message": "No relevant news found", "summary": [], "cards": [], "articles": []}
    qid = save_run("q", None, empty, path=db)
    run = get_run(qid, path=db)
    assert run.status == "no_news" and run.message == "No relevant news found"
    assert run.cards == [] and run.summary == []


def test_list_runs_newest_first_and_limit(db):
    ids = [save_run(f"q{i}", None, ok_result(), path=db) for i in range(3)]
    runs = list_runs(limit=2, path=db)
    assert [r["query_id"] for r in runs] == [ids[2], ids[1]]
    assert runs[0]["question"] == "q2" and runs[0]["status"] == "ok" and runs[0]["created_at"]


def test_evidence_is_saved_and_read_back(db):
    r = ok_result()
    r["cards"] = [card(1, evidence="Duty is 40 percent"), card(2)]
    qid = save_run("q", None, r, path=db)
    assert get_run(qid, path=db).cards[0].evidence == "Duty is 40 percent"


def test_old_db_without_evidence_column_is_migrated(db):
    with sqlite3.connect(db) as conn:  # the schema before the evidence column existed
        conn.executescript(
            "CREATE TABLE impacts (id INTEGER PRIMARY KEY AUTOINCREMENT, article_id INTEGER NOT NULL,"
            " relevant INTEGER NOT NULL, summary TEXT NOT NULL, sentiment TEXT NOT NULL,"
            " level TEXT NOT NULL, reason TEXT NOT NULL, horizon TEXT NOT NULL);"
        )
    conn.close()
    qid = save_run("q", None, ok_result(), path=db)
    assert len(get_run(qid, path=db).cards) == 2


def test_get_missing_id_returns_none(db):
    assert get_run(999, path=db) is None


def test_failed_save_leaves_nothing_behind(db):
    bad = ok_result()
    bad["cards"] = [card(1), card(42)]  # no article 42: save must roll back
    with pytest.raises(KeyError):
        save_run("q", None, bad, path=db)
    assert list_runs(path=db) == []
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0
