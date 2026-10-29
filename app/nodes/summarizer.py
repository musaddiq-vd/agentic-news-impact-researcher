"""Write 3-5 summary points from the relevant impact cards only."""

import logging

from pydantic import BaseModel

from app.config import get_settings
from app.llm import get_llm
from app.prompts import SUMMARY_SYSTEM, SUMMARY_USER
from app.schemas import Article, ImpactCard, SummaryPoint

log = logging.getLogger(__name__)
MAX_POINTS = 5
RETRIES = 1


class SummaryOutput(BaseModel):
    points: list[SummaryPoint]


def _items(cards: list[ImpactCard], articles: list[Article]) -> str:
    """One line per relevant card; the LLM sees card text, never raw article text or URLs."""
    by_id = {a.id: a for a in articles}
    lines = []
    for c in cards:
        a = by_id.get(c.article_id)
        if a is None or not c.relevant:
            continue
        lines.append(
            f"[{a.id}] {a.published_date.isoformat()} | {a.title} | {c.summary} "
            f"| impact: {c.sentiment}, {c.level}, {c.horizon} term | why: {c.reason}"
        )
    return "\n".join(lines)


def summarize(
    question: str,
    cards: list[ImpactCard],
    articles: list[Article],
    llm=None,
) -> list[SummaryPoint]:
    """Return up to 5 points; an empty list means the summary could not be made."""
    items = _items(cards, articles)
    if not items:
        return []
    llm = llm or get_llm(get_settings().model_summary)
    chain = llm.with_structured_output(SummaryOutput)
    messages = [
        ("system", SUMMARY_SYSTEM),
        ("user", SUMMARY_USER.format(question=question, items=items)),
    ]
    for _ in range(RETRIES + 1):
        try:
            points = chain.invoke(messages).points
        except Exception as exc:
            log.warning("summarizer failed: %s", exc)
            continue
        if points:
            return points[:MAX_POINTS]
    return []
