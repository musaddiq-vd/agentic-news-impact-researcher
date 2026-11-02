import pytest

from app import trace
from app.graph import Nodes, run_graph
from app.schemas import Article, CardOut, ImpactCard, RawArticle, SummaryOut, SummaryPoint


def test_emit_reaches_the_listener_only_inside_listen():
    seen = []
    with trace.listen(seen.append):
        trace.emit("merge", "done", "5 unique articles", count=5)
    trace.emit("merge", "done", "not heard")
    assert len(seen) == 1
    assert seen[0]["agent"] == "merge" and seen[0]["count"] == 5 and "t" in seen[0]


def test_step_emits_start_and_done_with_duration():
    seen = []
    with trace.listen(seen.append), trace.step("filter_rank", "ranking") as s:
        s["done"] = "kept 3"
    assert [e["event"] for e in seen] == ["start", "done"]
    assert seen[1]["message"] == "kept 3" and seen[1]["ms"] >= 0


def test_step_emits_error_and_reraises():
    seen = []
    with pytest.raises(ValueError), trace.listen(seen.append), trace.step("validator", "checking"):
        raise ValueError("boom")
    assert seen[-1]["event"] == "error" and "boom" in seen[-1]["message"]


def test_broken_listener_does_not_break_the_run():
    def bad(ev):
        raise RuntimeError("x")

    with trace.listen(bad):
        trace.emit("merge", "done", "fine")


def test_terminal_lines_and_switch(capsys, monkeypatch):
    monkeypatch.setenv("TRACE_LOGS", "1")
    with trace.run("my question") as outcome:
        trace.emit("search_1", "done", "4 articles found", ms=1200)
        outcome["status"] = "ok"
    err = capsys.readouterr().err
    assert "my question" in err and "search_1" in err and "4 articles found" in err and "(1.20s)" in err
    assert "ok in" in err

    monkeypatch.setenv("TRACE_LOGS", "0")
    with trace.run("quiet"):
        trace.emit("merge", "done", "hidden")
    assert capsys.readouterr().err == ""


def test_events_from_parallel_search_agents_reach_the_listener():
    art = Article(id=1, title="t", url="https://s.com/1", source="s.com",
                  published_date="2026-10-29", content="c", is_today_or_yesterday=True)
    card = ImpactCard(article_id=1, relevant=True, summary="s", sentiment="negative",
                      level="high", reason="r", horizon="short")
    out = CardOut(**card.model_dump(), title="t", url="https://s.com/1", source="s.com", published_date="2026-10-29")
    n = Nodes(
        build_queries=lambda *a: ["q1", "q2", "q3"],
        search=lambda qs: [RawArticle(title="t", url=f"https://s.com/{qs[0]}", content="c")],
        rank=lambda raw: [art],
        analyze=lambda q, a: [card],
        summarize=lambda *a: ([SummaryPoint(text="p", source_ids=[1])], True),
        validate=lambda *a: ([out], [SummaryOut(text="p", sources=["https://s.com/1"])]),
    )
    seen = []
    with trace.listen(seen.append):
        assert run_graph("q", nodes=n)["status"] == "ok"
    done = {e["agent"] for e in seen if e["event"] == "done"}
    assert {"query_builder", "search_1", "search_2", "search_3", "merge", "filter_rank",
            "impact_analyzer", "summarizer", "validator"} <= done
