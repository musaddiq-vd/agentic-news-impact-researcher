"""Quality checks for one real run. Pure functions: they only read the run_graph result."""

import re
from dataclasses import dataclass
from datetime import date, timedelta

RELEVANCE_SHARE = 0.5  # at least half the cards must mention one of the case's keywords


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def check_run(case: dict, result: dict, today: date, days: int = 30) -> list[Check]:
    """Every rule from the requirements that can be checked without a human."""
    expect = case["expect"]
    cards, summary, articles = result["cards"], result["summary"], result["articles"]
    checks = [Check(
        "status", result["status"] in expect["status"],
        f"got {result['status']}, expected {' or '.join(expect['status'])}",
    )]

    if expect.get("out_of_scope"):
        checks.append(Check("no_cards_off_topic", not cards, f"{len(cards)} cards for an off-topic question"))
        return checks
    if result["status"] != "ok":
        return checks  # an allowed no_news has nothing more to check

    checks.append(Check("has_cards", len(cards) >= expect.get("min_cards", 1), f"{len(cards)} cards"))

    urls = {c.url for c in cards} | {a.url for a in articles}
    bad = [p.text[:50] for p in summary if not p.sources or not set(p.sources) <= urls]
    checks.append(Check("summary_sources", not bad, f"points without a valid source: {bad}"))

    oldest = today - timedelta(days=days)
    old = [c.title[:50] for c in cards if not oldest <= c.published_date <= today]
    checks.append(Check("dates_in_window", not old, f"outside the last {days} days: {old}"))

    flags = [a.is_today_or_yesterday for a in articles]
    checks.append(Check("fresh_first", flags == sorted(flags, reverse=True), "today/yesterday news is not first"))

    by_id = {a.id: _norm(a.content) for a in articles}
    unquoted = [c.title[:50] for c in cards if c.evidence and _norm(c.evidence) not in by_id.get(c.article_id, "")]
    checks.append(Check("evidence_is_quoted", not unquoted, f"evidence not found in the article: {unquoted}"))

    texts = [p.text for p in summary] + [c.reason for c in cards] + [c.summary for c in cards]
    with_url = [t[:50] for t in texts if "http" in t or "www." in t]
    checks.append(Check("no_urls_in_text", not with_url, f"LLM text with a URL: {with_url}"))

    keywords = [k.lower() for k in expect.get("keywords", [])]
    if keywords and cards:
        hits = sum(any(k in _norm(f"{c.title} {c.summary} {c.evidence}") for k in keywords) for c in cards)
        share = hits / len(cards)
        checks.append(Check("on_topic", share >= RELEVANCE_SHARE, f"{hits}/{len(cards)} cards mention {keywords}"))
    return checks


def score(checks: list[Check]) -> float:
    return sum(c.passed for c in checks) / len(checks) if checks else 0.0
