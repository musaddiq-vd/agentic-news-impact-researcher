"""Drop unsupported LLM output (pure code, no LLM)."""

import re

from app.schemas import Article, CardOut, ImpactCard, SummaryOut, SummaryPoint

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str) -> set[str]:
    """Numbers in text, normalized (thousands commas removed, trailing '.' dropped)."""
    return {m.replace(",", "").rstrip(".") for m in _NUMBER.findall(text)}


def _supported(text: str, sources: list[Article]) -> bool:
    """True if every number in text also appears in the source articles."""
    allowed: set[str] = set()
    for a in sources:
        allowed |= _numbers(f"{a.title} {a.content}")
    return _numbers(text) <= allowed


def validate(
    cards: list[ImpactCard],
    points: list[SummaryPoint],
    articles: list[Article],
) -> tuple[list[CardOut], list[SummaryOut]]:
    """Return clean cards and summary points; the URLs are added here, not by the LLM."""
    by_id = {a.id: a for a in articles}

    clean_cards: list[CardOut] = []
    for c in cards:
        art = by_id.get(c.article_id)
        if art is None or not c.relevant:
            continue
        if not _supported(f"{c.summary} {c.reason}", [art]):
            continue
        clean_cards.append(
            CardOut(
                **c.model_dump(),
                title=art.title,
                url=art.url,
                source=art.source,
                published_date=art.published_date,
            )
        )

    kept_ids = {c.article_id for c in clean_cards}
    clean_points: list[SummaryOut] = []
    for p in points:
        ids = [i for i in dict.fromkeys(p.source_ids) if i in kept_ids]
        if not ids:
            continue
        sources = [by_id[i] for i in ids]
        if not _supported(p.text, sources):
            continue
        clean_points.append(SummaryOut(text=p.text, sources=[a.url for a in sources]))

    return clean_cards, clean_points
