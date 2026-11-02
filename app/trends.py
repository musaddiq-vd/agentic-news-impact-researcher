"""Sentiment trends over saved impact cards: overall mood, per day and per theme."""

from datetime import date, timedelta

# Theme -> keywords looked for in the title and summary. An article can match several themes.
THEMES = {
    "Coal": ["coal"],
    "Crude oil": ["crude", "brent", "oil price"],
    "Power tariff": ["tariff", "electricity", "power price", "discom"],
    "Cells & polysilicon": ["polysilicon", "wafer", "solar cell", "cell price"],
    "Policy": ["almm", "bcd", "pli", "surya ghar", "policy", "duty", "mnre", "ministry"],
    "Markets & stocks": ["nifty", "sensex", "stock", "share", "ipo"],
    "Demand & projects": ["rooftop", "tender", "capacity", "project", "order"],
}
SENTIMENTS = ("positive", "negative", "neutral")
STEADY_BAND = 20  # score change (points) below which a theme counts as steady


def score(rows: list[dict]) -> int | None:
    """Mood from -100 (all negative) to +100 (all positive); None when there is no news."""
    if not rows:
        return None
    pos = sum(r["sentiment"] == "positive" for r in rows)
    neg = sum(r["sentiment"] == "negative" for r in rows)
    return round((pos - neg) / len(rows) * 100)


def _counts(rows: list[dict]) -> dict[str, int]:
    return {s: sum(r["sentiment"] == s for r in rows) for s in SENTIMENTS}


def _themes_of(row: dict) -> list[str]:
    text = f"{row['title']} {row['summary']}".lower()
    return [t for t, words in THEMES.items() if any(w in text for w in words)]


def _direction(before: int | None, after: int | None) -> str:
    if after is None:
        return "quiet"
    if before is None:
        return "new"
    change = after - before
    if abs(change) < STEADY_BAND:
        return "steady"
    return "better" if change > 0 else "worse"


def build_trends(rows: list[dict], days: int, today: date) -> dict:
    """Compare the older half of the window with the recent half to show where mood is heading."""
    start = today - timedelta(days=days - 1)
    split = today - timedelta(days=days // 2 - 1)  # first day of the recent half
    rows = [r for r in rows if start.isoformat() <= r["published_date"] <= today.isoformat()]
    earlier = [r for r in rows if r["published_date"] < split.isoformat()]
    recent = [r for r in rows if r["published_date"] >= split.isoformat()]

    daily = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        daily.append({"date": d, **_counts([r for r in rows if r["published_date"] == d])})

    themes = []
    for theme in THEMES:
        mine = [r for r in rows if theme in _themes_of(r)]
        if not mine:
            continue
        before = score([r for r in mine if r in earlier])
        after = score([r for r in mine if r in recent])
        latest = max(mine, key=lambda r: r["published_date"])
        themes.append({
            "theme": theme,
            "count": len(mine),
            **_counts(mine),
            "score": score(mine),
            "earlier_score": before,
            "recent_score": after,
            "direction": _direction(before, after),
            "latest": {k: latest[k] for k in ("title", "url", "sentiment", "published_date")},
        })
    themes.sort(key=lambda t: t["count"], reverse=True)

    overall_before, overall_after = score(earlier), score(recent)
    return {
        "days": days,
        "total": len(rows),
        "overall": {
            **_counts(rows),
            "score": score(rows),
            "earlier_score": overall_before,
            "recent_score": overall_after,
            "direction": _direction(overall_before, overall_after),
        },
        "daily": daily,
        "themes": themes,
        "highlights": _highlights(themes),
    }


def _highlights(themes: list[dict]) -> list[str]:
    """Short plain-English lines for the themes that moved the most."""
    lines = []
    moved = [t for t in themes if t["direction"] in ("better", "worse")]
    moved.sort(key=lambda t: abs(t["recent_score"] - t["earlier_score"]), reverse=True)
    for t in moved[:3]:
        word = "more negative" if t["direction"] == "worse" else "more positive"
        lines.append(
            f"{t['theme']} news is turning {word} ({t['earlier_score']:+d} → {t['recent_score']:+d})"
        )
    for t in themes:
        if t["direction"] == "new" and len(lines) < 4:
            lines.append(f"{t['theme']} is a new topic in recent news ({t['count']} articles)")
    return lines
