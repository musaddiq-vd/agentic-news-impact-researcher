"""Drop unsupported LLM output (pure code, no LLM)."""

import re

from app.schemas import Article, CardOut, ImpactCard, SummaryOut, SummaryPoint

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[a-z]{4,}")
_STOP = set(
    "that this with from have will been were their they them which while also into than then "
    "more most some such about over under after before between during these those there here "
    "would could should being only very just like".split()
)
# Share of a summary point's content words that must appear in its cited sources.
# Measured on live runs: invented claims scored 0.50-0.62, news-based points 0.64-1.00.
GROUNDING_MIN = 0.7


def _numbers(text: str) -> set[str]:
    """Numbers in text, normalized (thousands commas removed, trailing '.' dropped)."""
    return {m.replace(",", "").rstrip(".") for m in _NUMBER.findall(text)}


def _supported(text: str, sources: list[Article]) -> bool:
    """True if every number in text also appears in the source articles."""
    allowed: set[str] = set()
    for a in sources:
        allowed |= _numbers(f"{a.title} {a.content}")
    return _numbers(text) <= allowed


def _stems(text: str) -> set[str]:
    """Content words cut to 5 letters, so plurals and verb forms still match."""
    return {w[:5] for w in _WORD.findall(text.lower()) if w not in _STOP}


def _grounded(text: str, vocabulary: str) -> bool:
    """True if enough of the text's content words appear in the vocabulary text."""
    words = _stems(text)
    if not words:
        return True
    return len(words & _stems(vocabulary)) / len(words) >= GROUNDING_MIN


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
    card_text = {c.article_id: f"{c.summary} {c.reason}" for c in clean_cards}
    clean_points: list[SummaryOut] = []
    for p in points:
        ids = [i for i in dict.fromkeys(p.source_ids) if i in kept_ids]
        if not ids:
            continue
        sources = [by_id[i] for i in ids]
        if not _supported(p.text, sources):
            continue
        vocabulary = " ".join(f"{a.title} {a.content} {card_text[a.id]}" for a in sources)
        if not _grounded(p.text, vocabulary):
            continue
        clean_points.append(SummaryOut(text=p.text, sources=[a.url for a in sources]))

    return clean_cards, clean_points
