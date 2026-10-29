"""Run search queries on Tavily and return raw, deduped results."""

import logging
from datetime import datetime, timedelta

from app.config import IST, get_settings
from app.schemas import RawArticle

log = logging.getLogger(__name__)
RETRIES = 1


class SearchError(Exception):
    """Raised when every query fails, even after retries."""


def _make_tool(max_results: int):
    from langchain_tavily import TavilySearch  # lazy: keeps mocked tests import-free

    get_settings()  # loads .env so TAVILY_API_KEY is in the environment
    return TavilySearch(max_results=max_results, topic="news", search_depth="basic")


def _search_one(tool, query: str, start: str, end: str) -> list[dict]:
    """One query with retries; raises the last error if all attempts fail."""
    last: Exception | None = None
    for _ in range(RETRIES + 1):
        try:
            response = tool.invoke({"query": query, "start_date": start, "end_date": end})
            return response["results"]
        except Exception as exc:
            last = exc
    raise last  # type: ignore[misc]


def search_news(
    queries: list[str],
    days: int | None = None,
    max_results: int = 8,
    tool=None,
    now: datetime | None = None,
) -> list[RawArticle]:
    """Search every query for news in the last `days` days. Fails only if all queries fail."""
    days = days if days is not None else get_settings().days
    end_date = (now or datetime.now(IST)).astimezone(IST).date()
    start, end = (end_date - timedelta(days=days)).isoformat(), end_date.isoformat()
    tool = tool or _make_tool(max_results)

    articles: list[RawArticle] = []
    seen: set[str] = set()
    failures = 0
    for query in queries:
        try:
            results = _search_one(tool, query, start, end)
        except Exception as exc:
            failures += 1
            log.warning("search failed for %r: %s", query, exc)
            continue
        for r in results:
            url = (r.get("url") or "").strip()
            key = url.rstrip("/").lower()
            if not url or key in seen:
                continue
            seen.add(key)
            articles.append(
                RawArticle(
                    title=r.get("title") or "",
                    url=url,
                    content=r.get("content") or "",
                    published_date=r.get("published_date"),
                    score=r.get("score") or 0.0,
                )
            )

    if queries and failures == len(queries):
        raise SearchError("all search queries failed")
    return articles
