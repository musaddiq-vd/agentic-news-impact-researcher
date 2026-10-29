"""Drop unsupported LLM output (pure code, no LLM)."""

import logging
import re

from app.schemas import Article, CardOut, ImpactCard, SummaryOut, SummaryPoint

log = logging.getLogger(__name__)

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


def _stems(text: str, n: int = 5) -> set[str]:
    """Content words cut to n letters, so plurals and verb forms still match."""
    return {w[:n] for w in _WORD.findall(text.lower()) if w not in _STOP}


def _grounding(text: str, vocabulary: str) -> float:
    """Share of the text's content words that appear in the vocabulary text (1.0 if none)."""
    words = _stems(text)
    if not words:
        return 1.0
    return len(words & _stems(vocabulary)) / len(words)


# Share of the evidence's 5-word sequences that must appear in the article, so a
# quote may differ in a word or two but cannot be made up.
QUOTE_MIN = 0.6
_TOKEN = re.compile(r"[a-z0-9]+")


def _quoted(evidence: str, text: str) -> bool:
    """True if the evidence is (nearly) a word-for-word passage of the text."""
    ev = _TOKEN.findall(evidence.lower())
    if not ev:
        return False
    words = _TOKEN.findall(text.lower())
    n = min(5, len(ev))
    have = {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}
    grams = [tuple(ev[i:i + n]) for i in range(len(ev) - n + 1)]
    return sum(g in have for g in grams) / len(grams) >= QUOTE_MIN


def _short(text: str, n: int = 80) -> str:
    return text if len(text) <= n else text[:n] + "..."


def validate(
    cards: list[ImpactCard],
    points: list[SummaryPoint],
    articles: list[Article],
    question_text: str = "",
) -> tuple[list[CardOut], list[SummaryOut]]:
    """Return clean cards and summary points; the URLs are added here, not by the LLM.

    `question_text` (the question and the search queries) lets us catch a point that
    repeats the question's own words without its sources saying them.
    """
    by_id = {a.id: a for a in articles}
    question_stems = _stems(question_text, 4)

    clean_cards: list[CardOut] = []
    for c in cards:
        art = by_id.get(c.article_id)
        if art is None:
            log.warning("dropped card: unknown article id %s", c.article_id)
            continue
        if not c.relevant:
            continue
        article_text = f"{art.title} {art.content}"
        if not _quoted(c.evidence, article_text):
            log.warning("dropped card %s: evidence not found in the article: %r", c.article_id, _short(c.evidence))
            continue
        if not _supported(f"{c.summary} {c.reason} {c.evidence}", [art]):
            log.warning("dropped card %s: number not found in the article", c.article_id)
            continue
        score = _grounding(c.summary, article_text)
        if score < GROUNDING_MIN:
            log.warning("dropped card %s: summary grounding %.2f < %.2f", c.article_id, score, GROUNDING_MIN)
            continue
        leaked = (_stems(c.summary, 4) & question_stems) - _stems(article_text, 4)
        if leaked:
            log.warning("dropped card %s: summary has question terms %s not in the article", c.article_id, sorted(leaked))
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
    # Only the card's summary of the article counts as a source. Its "reason" is the
    # model's own inference, so a point must not be allowed to borrow words from it.
    card_text = {c.article_id: c.summary for c in clean_cards}
    clean_points: list[SummaryOut] = []
    for p in points:
        ids = [i for i in dict.fromkeys(p.source_ids) if i in kept_ids]
        if not ids:
            log.warning("dropped point: no valid source %s: %r", p.source_ids, _short(p.text))
            continue
        sources = [by_id[i] for i in ids]
        if not _supported(p.text, sources):
            log.warning("dropped point: number not found in sources: %r", _short(p.text))
            continue
        vocabulary = " ".join(f"{a.title} {a.content} {card_text[a.id]}" for a in sources)
        score = _grounding(p.text, vocabulary)
        if score < GROUNDING_MIN:
            log.warning("dropped point: grounding %.2f < %.2f: %r", score, GROUNDING_MIN, _short(p.text))
            continue
        leaked = (_stems(p.text, 4) & question_stems) - _stems(vocabulary, 4)
        if leaked:
            log.warning("dropped point: question terms %s not in its sources: %r", sorted(leaked), _short(p.text))
            continue
        clean_points.append(SummaryOut(text=p.text, sources=[a.url for a in sources]))

    return clean_cards, clean_points
