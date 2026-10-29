"""LangGraph flow: question -> queries -> search -> rank -> impact -> summary -> validate."""

import logging
import sys
from dataclasses import dataclass
from functools import wraps
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.nodes.filter_rank import filter_rank
from app.nodes.impact_analyzer import analyze_impacts
from app.nodes.news_search import SearchError, search_news
from app.nodes.query_builder import build_queries
from app.nodes.summarizer import summarize
from app.nodes.validator import validate
from app.schemas import Article, CardOut, ImpactCard, RawArticle, SummaryOut, SummaryPoint

log = logging.getLogger(__name__)

MSG_NO_NEWS = "No relevant news found for this topic in the last 30 days."
MSG_SEARCH_DOWN = "Search is not available right now."
MSG_ERROR = "Something went wrong. Please try again."
MSG_NO_SUMMARY = "Summary could not be generated."


class GraphState(TypedDict, total=False):
    question: str
    topic: str | None
    competitors: list[str]
    queries: list[str]
    raw_results: list[RawArticle]
    articles: list[Article]
    cards: list[ImpactCard]
    points: list[SummaryPoint]
    out_cards: list[CardOut]
    out_summary: list[SummaryOut]
    status: str
    message: str | None


@dataclass
class Nodes:
    """The functions the graph calls; tests replace them with fakes."""

    build_queries: Callable
    search: Callable
    rank: Callable
    analyze: Callable
    summarize: Callable
    validate: Callable


def default_nodes() -> Nodes:
    s = get_settings()
    return Nodes(
        build_queries=build_queries,
        search=lambda queries: search_news(queries, days=s.days, max_results=s.max_articles),
        rank=lambda raw: filter_rank(raw, days=s.days, max_articles=s.max_articles),
        analyze=analyze_impacts,
        summarize=summarize,
        validate=validate,
    )


def _safe(fn):
    """Turn exceptions into an error status so the graph never crashes."""

    @wraps(fn)
    def inner(state: GraphState) -> GraphState:
        try:
            return fn(state)
        except SearchError:
            return {"status": "error", "message": MSG_SEARCH_DOWN}
        except Exception:
            log.exception("graph node failed: %s", fn.__name__)
            return {"status": "error", "message": MSG_ERROR}

    return inner


def _route(state: GraphState) -> str:
    return "stop" if state.get("status") in ("error", "no_news") else "continue"


def build_graph(nodes: Nodes | None = None):
    n = nodes or default_nodes()

    @_safe
    def queries_node(state: GraphState) -> GraphState:
        return {"queries": n.build_queries(state["question"], state.get("topic"), state.get("competitors"))}

    @_safe
    def search_node(state: GraphState) -> GraphState:
        return {"raw_results": n.search(state["queries"])}

    @_safe
    def rank_node(state: GraphState) -> GraphState:
        articles = n.rank(state["raw_results"])
        if not articles:
            return {"articles": [], "status": "no_news", "message": MSG_NO_NEWS}
        return {"articles": articles}

    @_safe
    def impact_node(state: GraphState) -> GraphState:
        cards = n.analyze(state["question"], state["articles"])
        if not cards:
            # Every analysis call failed: that is an error, not "no news".
            return {"status": "error", "message": MSG_ERROR}
        if not any(c.relevant for c in cards):
            return {"cards": cards, "status": "no_news", "message": MSG_NO_NEWS}
        return {"cards": cards}

    def summary_node(state: GraphState) -> GraphState:
        # A failed summary is not fatal: cards are still shown.
        try:
            return {"points": n.summarize(state["question"], state["cards"], state["articles"])}
        except Exception:
            log.exception("summarizer failed")
            return {"points": []}

    @_safe
    def validate_node(state: GraphState) -> GraphState:
        cards, summary = n.validate(state["cards"], state["points"], state["articles"])
        if not cards:
            return {"status": "no_news", "message": MSG_NO_NEWS}
        return {
            "out_cards": cards,
            "out_summary": summary,
            "status": "ok",
            "message": None if summary else MSG_NO_SUMMARY,
        }

    g = StateGraph(GraphState)
    # Node names must differ from state keys, hence the "_node" suffix.
    for name, fn in [
        ("queries_node", queries_node), ("search_node", search_node), ("rank_node", rank_node),
        ("impact_node", impact_node), ("summary_node", summary_node), ("validate_node", validate_node),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "queries_node")
    g.add_edge("queries_node", "search_node")
    g.add_conditional_edges("search_node", _route, {"continue": "rank_node", "stop": END})
    g.add_conditional_edges("rank_node", _route, {"continue": "impact_node", "stop": END})
    g.add_conditional_edges("impact_node", _route, {"continue": "summary_node", "stop": END})
    g.add_edge("summary_node", "validate_node")
    g.add_edge("validate_node", END)
    return g.compile()


def run_graph(
    question: str,
    topic: str | None = None,
    competitors: list[str] | None = None,
    nodes: Nodes | None = None,
) -> dict:
    """Run the flow; returns status, message, summary (with URLs) and cards. Never saves to the DB."""
    final = build_graph(nodes).invoke(
        {"question": question, "topic": topic, "competitors": competitors or []}
    )
    return {
        "status": final.get("status", "error"),
        "message": final.get("message"),
        "summary": final.get("out_summary", []),
        "cards": final.get("out_cards", []),
    }


if __name__ == "__main__":
    # Manual check: python -m app.graph "your question" [topic]
    result = run_graph(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"status: {result['status']}  message: {result['message']}")
    for p in result["summary"]:
        print(f"\n* {p.text}")
        for url in p.sources:
            print(f"    {url}")
    for c in result["cards"]:
        print(f"\n[{c.published_date}] {c.title}\n  {c.sentiment}/{c.level}/{c.horizon}: {c.reason}\n  {c.url}")
