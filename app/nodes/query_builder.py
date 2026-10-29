"""Turn the user's question into 2-4 English search queries."""

import logging

from pydantic import BaseModel

from app.config import get_settings
from app.llm import get_llm
from app.prompts import QUERY_BUILDER_SYSTEM, QUERY_BUILDER_USER

log = logging.getLogger(__name__)
MAX_QUERIES = 4


class QueryList(BaseModel):
    queries: list[str]


def generate_queries(
    question: str,
    topic: str | None = None,
    competitors: list[str] | None = None,
    llm=None,
) -> list[str]:
    """Call the LLM; raises on failure."""
    llm = llm or get_llm(get_settings().model_query)
    chain = llm.with_structured_output(QueryList)
    result = chain.invoke(
        [
            ("system", QUERY_BUILDER_SYSTEM),
            (
                "user",
                QUERY_BUILDER_USER.format(
                    question=question,
                    topic=topic or "any",
                    competitors=", ".join(competitors or []) or "none",
                ),
            ),
        ]
    )
    queries = [q.strip() for q in result.queries if q and q.strip()]
    return list(dict.fromkeys(queries))[:MAX_QUERIES]


def build_queries(
    question: str,
    topic: str | None = None,
    competitors: list[str] | None = None,
    llm=None,
) -> list[str]:
    """Like generate_queries, but falls back to the raw question on any failure."""
    try:
        queries = generate_queries(question, topic, competitors, llm)
    except Exception as exc:
        log.warning("query_builder failed, using the question as query: %s", exc)
        return [question]
    return queries or [question]
