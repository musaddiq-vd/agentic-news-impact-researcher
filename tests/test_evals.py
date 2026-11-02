import json
from datetime import date

from app.schemas import Article, CardOut, SummaryOut
from evals import run as ev
from evals.checks import check_run

TODAY = date(2026, 11, 3)
CASE = {"id": "coal", "question": "coal?", "topic": "energy prices",
        "expect": {"status": ["ok"], "keywords": ["coal"]}}


def article(i, content="Coal prices rose 5% this week.", fresh=True, day="2026-11-02"):
    return Article(id=i, title=f"t{i}", url=f"https://s.com/{i}", source="s.com",
                   published_date=day, content=content, is_today_or_yesterday=fresh)


def card(i, title="Coal up", evidence="Coal prices rose 5%", day="2026-11-02", reason="Costs may rise."):
    return CardOut(article_id=i, relevant=True, summary="Coal prices rose.", sentiment="negative", level="high",
                   reason=reason, horizon="short", evidence=evidence, title=title, url=f"https://s.com/{i}",
                   source="s.com", published_date=day)


def result(cards=None, articles=None, summary=None, status="ok"):
    return {"status": status, "message": None,
            "cards": [card(1)] if cards is None else cards,
            "articles": [article(1)] if articles is None else articles,
            "summary": [SummaryOut(text="Coal rose.", sources=["https://s.com/1"])] if summary is None else summary}


def failed(checks):
    return {c.name for c in checks if not c.passed}


def test_good_run_passes_every_check():
    checks = check_run(CASE, result(), TODAY)
    assert failed(checks) == set()
    assert {c.name for c in checks} >= {"status", "has_cards", "summary_sources", "dates_in_window",
                                        "fresh_first", "evidence_is_quoted", "no_urls_in_text", "on_topic"}


def test_each_rule_is_caught():
    bad = result(
        cards=[card(1, evidence="made up quote", day="2026-09-01", reason="See https://x.com"),
               card(2, title="Cricket", evidence="")],
        articles=[article(1, fresh=False), article(2, fresh=True)],
        summary=[SummaryOut(text="x", sources=["https://unknown.com"])],
    )
    for c in bad["cards"][1:]:
        c.summary = "Sports."
    assert failed(check_run(CASE, bad, TODAY)) == {
        "summary_sources", "dates_in_window", "fresh_first", "evidence_is_quoted", "no_urls_in_text",
    }
    for c in bad["cards"]:
        c.title, c.summary = "Cricket", "Sports."
    assert "on_topic" in failed(check_run(CASE, bad, TODAY))


def test_off_topic_must_have_no_cards():
    case = {**CASE, "expect": {"status": ["no_news"], "out_of_scope": True}}
    assert failed(check_run(case, result(status="ok"), TODAY)) == {"status", "no_cards_off_topic"}
    assert failed(check_run(case, result(cards=[], status="no_news"), TODAY)) == set()


def test_allowed_no_news_stops_there():
    case = {**CASE, "expect": {"status": ["ok", "no_news"], "keywords": ["coal"]}}
    checks = check_run(case, result(cards=[], status="no_news"), TODAY)
    assert [c.name for c in checks] == ["status"] and checks[0].passed


def test_runner_scores_saves_and_flags_regressions(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRACE_LOGS", "0")  # main() sets it; monkeypatch restores it afterwards
    monkeypatch.setattr(ev, "RESULTS", tmp_path)
    monkeypatch.setattr(ev, "load_cases", lambda only=None: [CASE])
    base = {"score": 1.0, "cases": [{"id": "coal", "score": 1.0, "checks": []}]}
    (tmp_path / "2026-01-01_000000.json").write_text(json.dumps(base), encoding="utf-8")

    def broken(question, topic):
        return result(summary=[SummaryOut(text="x", sources=["https://unknown.com"])])

    assert ev.main([], runner=broken) == 1
    out = capsys.readouterr().out
    assert "REGRESSION" in out and "summary_sources" in out
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_crash_is_a_failed_case_not_a_crashed_eval():
    def boom(*a):
        raise RuntimeError("tavily down")

    row = ev.run_case(CASE, boom, TODAY)
    assert row["status"] == "crash" and row["score"] == 0 and "tavily down" in row["checks"][0]["detail"]


def test_cases_file_is_valid():
    cases = ev.load_cases()
    assert 10 <= len(cases) <= 15
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert c["question"] and c["topic"] and c["expect"]["status"]
