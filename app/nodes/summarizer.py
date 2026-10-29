"""Write up to 5 fact-only summary points from the relevant impact cards."""

import logging
from typing import NamedTuple

from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm import get_llm
from app.prompts import SUMMARY_SYSTEM, SUMMARY_USER
from app.schemas import Article, ImpactCard, SummaryPoint

log = logging.getLogger(__name__)
MAX_POINTS = 5
RETRIES = 1


class LLMPoint(BaseModel):
    """Lenient on purpose: a point without sources is dropped alone, not the whole summary."""

    text: str
    source_ids: list[int] = []


class SummaryOutput(BaseModel):
    # Field order matters: the model fills direct_item_ids first, then writes the points.
    direct_item_ids: list[int] | None = Field(
        default=None,
        description="IDs of the news items that directly discuss the specific thing the question "
        "asks about; an empty list if none does",
    )
    points: list[LLMPoint]


class SummaryResult(NamedTuple):
    points: list[SummaryPoint]
    answers_question: bool | None  # None = the model did not say


def _items(cards: list[ImpactCard], articles: list[Article]) -> str:
    """One line per relevant card: title and what the article says. No impact analysis, so the
    summary cannot repeat the analysis's guesses; the LLM never sees raw text or URLs."""
    by_id = {a.id: a for a in articles}
    lines = []
    for c in cards:
        a = by_id.get(c.article_id)
        if a is None or not c.relevant:
            continue
        lines.append(f"[{a.id}] {a.published_date.isoformat()} | {a.title} | {c.summary}")
    return "\n".join(lines)


def summarize(
    question: str,
    cards: list[ImpactCard],
    articles: list[Article],
    llm=None,
) -> SummaryResult:
    """Up to 5 points plus whether the news answers the question; no points = no summary."""
    items = _items(cards, articles)
    if not items:
        return SummaryResult([], None)
    llm = llm or get_llm(get_settings().model_summary)
    chain = llm.with_structured_output(SummaryOutput)
    messages = [
        ("system", SUMMARY_SYSTEM),
        ("user", SUMMARY_USER.format(question=question, items=items)),
    ]
    last_answers = None
    for _ in range(RETRIES + 1):
        try:
            output = chain.invoke(messages)
        except Exception as exc:
            log.warning("summarizer failed: %s", exc)
            continue
        # Rule 1: a point without a source is dropped.
        points = [
            SummaryPoint(text=p.text, source_ids=p.source_ids)
            for p in output.points
            if p.text.strip() and p.source_ids
        ]
        answers = _answers(output.direct_item_ids, cards, articles)
        if points:
            return SummaryResult(points[:MAX_POINTS], answers)
        log.warning("summarizer returned no usable points (%d raw, direct ids %s)",
                    len(output.points), output.direct_item_ids)
        last_answers = answers
    return SummaryResult([], last_answers)


def _answers(direct_ids: list[int] | None, cards: list[ImpactCard], articles: list[Article]) -> bool | None:
    """True if a real, shown item directly answers the question; None if the model did not say."""
    if direct_ids is None:
        return None
    shown = {a.id for a in articles} & {c.article_id for c in cards if c.relevant}
    return bool(shown & set(direct_ids))
