"""LangGraph flow: question -> queries -> 3 parallel searches -> merge -> rank -> impact -> summary -> validate."""

import logging
import operator
import sys
from dataclasses import dataclass
from functools import wraps
from typing import Annotated, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from app import trace
from app.config import get_settings
from app.nodes.filter_rank import filter_rank
from app.nodes.impact_analyzer import analyze_impacts
from app.nodes.news_search import SearchError, dedupe, search_news
from app.nodes.query_builder import build_queries
from app.nodes.summarizer import summarize
from app.nodes.validator import validate
from app.schemas import Article, CardOut, ImpactCard, RawArticle, SummaryOut

log = logging.getLogger(__name__)

MSG_NO_NEWS = "No relevant news found for this topic in the last 30 days."
MSG_SEARCH_DOWN = "Search is not available right now."
MSG_ERROR = "Something went wrong. Please try again."
MSG_NO_SUMMARY = "Summary could not be generated."
MSG_NOT_DIRECT = "News was found, but it does not directly answer your question."
SUMMARY_ATTEMPTS = 2
SEARCH_AGENTS = 3  # parallel search nodes; queries are dealt out round-robin
SEARCH_NODES = [f"search_{i + 1}" for i in range(SEARCH_AGENTS)]


class SearchPart(TypedDict):
    """What one search agent found. `error` is None, "search" (SearchError) or "other"."""

    agent: int
    ran: bool
    results: list[RawArticle]
    error: str | None


class GraphState(TypedDict, total=False):
    question: str
    topic: str | None
    queries: list[str]
    search_parts: Annotated[list[SearchPart], operator.add]  # one entry per search agent
    raw_results: list[RawArticle]
    articles: list[Article]
    cards: list[ImpactCard]
    checked: tuple[list[CardOut], list[SummaryOut]]
    answers: bool | None
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
        with trace.step("query_builder", "turning the question into search queries") as s:
            queries = n.build_queries(state["question"], state.get("topic"))
            s["done"] = f"{len(queries)} quer{'y' if len(queries) == 1 else 'ies'} ready"
            s["queries"] = queries
        return {"queries": queries}

    def make_search_node(agent: int):
        def search_node(state: GraphState) -> GraphState:
            """Search this agent's share of the queries. Never sets status: parallel nodes
            may not write the same key, so merge_node decides what a failure means."""
            name = SEARCH_NODES[agent]
            mine = state["queries"][agent::SEARCH_AGENTS]
            part: SearchPart = {"agent": agent, "ran": bool(mine), "results": [], "error": None}
            if not mine:
                trace.emit(name, "info", "no query for this agent, skipping")
            else:
                try:
                    with trace.step(name, " | ".join(f"“{q}”" for q in mine), queries=mine) as s:
                        part["results"] = n.search(mine)
                        s["done"] = f"{len(part['results'])} articles found"
                        s["count"] = len(part["results"])
                except SearchError as exc:
                    log.warning("search agent %d failed: %s", agent + 1, exc)
                    part["error"] = "search"
                except Exception:
                    log.exception("search agent %d crashed", agent + 1)
                    part["error"] = "other"
            return {"search_parts": [part]}

        return search_node

    @_safe
    def merge_node(state: GraphState) -> GraphState:
        """Join the agents' results. Fails only if every agent that had queries failed."""
        parts = sorted(state.get("search_parts", []), key=lambda p: p["agent"])
        ran = [p for p in parts if p["ran"]]
        if ran and all(p["error"] for p in ran):
            if all(p["error"] == "search" for p in ran):
                raise SearchError("all search agents failed")
            raise RuntimeError("search agents crashed")
        joined = [a for p in parts for a in p["results"]]
        unique = dedupe(joined)
        trace.emit(
            "merge", "done",
            f"{len(unique)} unique articles from {len(ran)} agents ({len(joined) - len(unique)} duplicates removed)",
            count=len(unique),
        )
        return {"raw_results": unique}

    @_safe
    def rank_node(state: GraphState) -> GraphState:
        with trace.step("filter_rank", f"checking dates and ranking {len(state['raw_results'])} articles") as s:
            articles = n.rank(state["raw_results"])
            fresh = sum(1 for a in articles if a.is_today_or_yesterday)
            merged = sum(len(a.also) for a in articles)
            s["done"] = f"kept {len(articles)} · {fresh} from today/yesterday" + (
                f" · merged {merged} duplicate report{'s' if merged != 1 else ''}" if merged else ""
            )
            s["count"] = len(articles)
        if not articles:
            return {"articles": [], "status": "no_news", "message": MSG_NO_NEWS}
        return {"articles": articles}

    @_safe
    def impact_node(state: GraphState) -> GraphState:
        total = len(state["articles"])
        with trace.step("impact_analyzer", f"analysing {total} articles in parallel", total=total) as s:
            cards = n.analyze(state["question"], state["articles"])
            s["done"] = f"{sum(c.relevant for c in cards)} of {total} articles affect the business"
        if not cards:
            # Every analysis call failed: that is an error, not "no news".
            return {"status": "error", "message": MSG_ERROR}
        if not any(c.relevant for c in cards):
            return {"cards": cards, "status": "no_news", "message": MSG_NO_NEWS}
        return {"cards": cards}

    @_safe
    def summary_node(state: GraphState) -> GraphState:
        """Summarize and validate; try again if no valid point survives (LLM output varies)."""
        checked, answers = ([], []), None
        for attempt in range(SUMMARY_ATTEMPTS):
            if attempt:
                trace.emit("summarizer", "warn", "no point survived the check, writing the summary again")
            try:
                with trace.step("summarizer", "writing fact-only summary points") as s:
                    points, answers = n.summarize(state["question"], state["cards"], state["articles"])
                    s["done"] = f"{len(points)} point{'' if len(points) == 1 else 's'} written"
            except Exception:
                # A failed summary is not fatal: cards are still shown.
                log.exception("summarizer failed")
                points, answers = [], None
            question_text = " ".join([state["question"], *state.get("queries", [])])
            with trace.step("validator", "checking every claim against its article") as s:
                checked = n.validate(state["cards"], points, state["articles"], question_text)
                s["done"] = f"{len(checked[0])} cards · {len(checked[1])} points backed by sources"
            if checked[1] or not checked[0]:
                break
        return {"checked": checked, "answers": answers}

    @_safe
    def final_node(state: GraphState) -> GraphState:
        cards, summary = state["checked"]
        if not cards:
            return {"status": "no_news", "message": MSG_NO_NEWS}
        if not summary:
            # No summary because the news does not answer the question is not a failure.
            message = MSG_NOT_DIRECT if state.get("answers") is False else MSG_NO_SUMMARY
        elif state.get("answers") is False:
            message = MSG_NOT_DIRECT  # honest note: related news, but not an answer
        else:
            message = None
        return {"out_cards": cards, "out_summary": summary, "status": "ok", "message": message}

    g = StateGraph(GraphState)
    # Node names must differ from state keys, hence the "_node" suffix.
    for name, fn in [
        ("queries_node", queries_node),
        *[(name, make_search_node(i)) for i, name in enumerate(SEARCH_NODES)],
        ("merge_node", merge_node), ("rank_node", rank_node),
        ("impact_node", impact_node), ("summary_node", summary_node), ("final_node", final_node),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "queries_node")
    # Fan out to the search agents (they run in parallel), then wait for all of them in merge_node.
    g.add_conditional_edges(
        "queries_node",
        lambda s: END if _route(s) == "stop" else SEARCH_NODES,
        [*SEARCH_NODES, END],
    )
    g.add_edge(SEARCH_NODES, "merge_node")
    g.add_conditional_edges("merge_node", _route, {"continue": "rank_node", "stop": END})
    g.add_conditional_edges("rank_node", _route, {"continue": "impact_node", "stop": END})
    g.add_conditional_edges("impact_node", _route, {"continue": "summary_node", "stop": END})
    g.add_conditional_edges("summary_node", _route, {"continue": "final_node", "stop": END})
    g.add_edge("final_node", END)
    return g.compile()


def run_graph(
    question: str,
    topic: str | None = None,
    nodes: Nodes | None = None,
) -> dict:
    """Run the flow; returns status, message, summary (with URLs), cards and ranked articles.

    Never saves to the DB; the caller (api.py) does that.
    """
    with trace.run(question) as outcome:
        final = build_graph(nodes).invoke(
            {"question": question, "topic": topic}
        )
        outcome["status"] = final.get("status", "error")
    return {
        "status": final.get("status", "error"),
        "message": final.get("message"),
        "summary": final.get("out_summary", []),
        "cards": final.get("out_cards", []),
        "articles": final.get("articles", []),
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
