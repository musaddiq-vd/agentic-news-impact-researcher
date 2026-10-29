from app.graph import (
    MSG_ERROR, MSG_NO_NEWS, MSG_NO_SUMMARY, MSG_SEARCH_DOWN, Nodes, run_graph,
)
from app.nodes.news_search import SearchError
from app.schemas import Article, CardOut, ImpactCard, RawArticle, SummaryOut, SummaryPoint


def article(i=1):
    return Article(
        id=i, title=f"t{i}", url=f"https://s.com/{i}", source="s.com",
        published_date="2026-10-29", content="c", is_today_or_yesterday=True,
    )


def card(i=1, relevant=True):
    return ImpactCard(
        article_id=i, relevant=relevant, summary="s", sentiment="negative",
        level="high", reason="r", horizon="short",
    )


def card_out(i=1):
    return CardOut(
        **card(i).model_dump(), title=f"t{i}", url=f"https://s.com/{i}",
        source="s.com", published_date="2026-10-29",
    )


class Calls(list):
    def rec(self, name, ret):
        def fn(*a, **k):
            self.append(name)
            if isinstance(ret, Exception):
                raise ret
            return ret() if callable(ret) else ret
        return fn


def nodes(calls, *, queries=("q",), search=None, rank=None, analyze=None,
          summary=None, validate=None):
    search = [RawArticle(title="t", url="https://s.com/1", content="c")] if search is None else search
    rank = [article()] if rank is None else rank
    analyze = [card()] if analyze is None else analyze
    summary = [SummaryPoint(text="p", source_ids=[1])] if summary is None else summary
    validate = ([card_out()], [SummaryOut(text="p", sources=["https://s.com/1"])]) if validate is None else validate
    return Nodes(
        build_queries=calls.rec("queries", list(queries)),
        search=calls.rec("search", search),
        rank=calls.rec("rank", rank),
        analyze=calls.rec("analyze", analyze),
        summarize=calls.rec("summarize", summary),
        validate=calls.rec("validate", validate),
    )


def test_happy_path_runs_every_node_in_order():
    calls = Calls()
    result = run_graph("q", nodes=nodes(calls))
    assert calls == ["queries", "search", "rank", "analyze", "summarize", "validate"]
    assert result["status"] == "ok" and result["message"] is None
    assert result["summary"][0].sources == ["https://s.com/1"]
    assert result["cards"][0].url == "https://s.com/1"


def test_no_articles_stops_with_no_news():
    calls = Calls()
    result = run_graph("q", nodes=nodes(calls, rank=[]))
    assert calls == ["queries", "search", "rank"]
    assert result["status"] == "no_news" and result["message"] == MSG_NO_NEWS
    assert result["cards"] == [] and result["summary"] == []


def test_no_relevant_cards_stops_with_no_news():
    calls = Calls()
    result = run_graph("q", nodes=nodes(calls, analyze=[card(relevant=False)]))
    assert calls[-1] == "analyze"
    assert result["status"] == "no_news"


def test_all_analyses_failing_is_error_not_no_news():
    result = run_graph("q", nodes=nodes(Calls(), analyze=[]))
    assert result["status"] == "error" and result["message"] == MSG_ERROR


def test_search_error_gives_error_status():
    calls = Calls()
    result = run_graph("q", nodes=nodes(calls, search=SearchError("down")))
    assert calls == ["queries", "search"]
    assert result["status"] == "error" and result["message"] == MSG_SEARCH_DOWN


def test_unexpected_error_gives_generic_error():
    result = run_graph("q", nodes=nodes(Calls(), analyze=RuntimeError("boom")))
    assert result["status"] == "error" and result["message"] == MSG_ERROR


def test_summary_failure_still_returns_cards():
    result = run_graph("q", nodes=nodes(Calls(), summary=RuntimeError("x"), validate=([card_out()], [])))
    assert result["status"] == "ok" and result["message"] == MSG_NO_SUMMARY
    assert len(result["cards"]) == 1 and result["summary"] == []


def test_empty_validated_summary_gives_message():
    result = run_graph("q", nodes=nodes(Calls(), validate=([card_out()], [])))
    assert result["status"] == "ok" and result["message"] == MSG_NO_SUMMARY


def test_validator_dropping_every_card_gives_no_news():
    result = run_graph("q", nodes=nodes(Calls(), validate=([], [])))
    assert result["status"] == "no_news" and result["cards"] == []


def test_question_topic_and_competitors_reach_query_builder():
    seen = {}

    def qb(question, topic, competitors):
        seen.update(question=question, topic=topic, competitors=competitors)
        return ["q"]

    n = nodes(Calls())
    n.build_queries = qb
    run_graph("my question", "policy", ["Waaree Energies"], nodes=n)
    assert seen == {"question": "my question", "topic": "policy", "competitors": ["Waaree Energies"]}
