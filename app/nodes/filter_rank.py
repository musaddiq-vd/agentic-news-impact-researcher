"""Filter and rank raw Tavily results (pure code, no LLM)."""

from datetime import date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from app.config import IST
from app.nodes.story_merge import group_stories
from app.schemas import Article, RawArticle, SourceRef


def parse_date(value: str | None) -> date | None:
    """Parse an ISO or RFC 2822 date string to an IST date; None if missing or invalid."""
    if not value:
        return None
    value = value.strip()
    dt = None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        return dt.date()  # no timezone info: take the date as given
    return dt.astimezone(IST).date()


def _source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.")


def filter_rank(
    raw: list[RawArticle],
    days: int = 30,
    max_articles: int = 8,
    now: datetime | None = None,
) -> list[Article]:
    """Drop undated/old/duplicate items, rank (today/yesterday, newest, Tavily score), then merge
    the same story from different sites into one article before keeping the top `max_articles`."""
    today = (now or datetime.now(IST)).astimezone(IST).date()
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    kept: list[tuple[RawArticle, date]] = []

    for item in raw:
        d = parse_date(item.published_date)
        if d is None or d > today or (today - d).days > days:
            continue
        url_key = item.url.strip().rstrip("/").lower()
        title_key = item.title.strip().lower()
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        kept.append((item, d))

    def is_recent(d: date) -> bool:
        return (today - d).days <= 1

    kept.sort(key=lambda x: (is_recent(x[1]), x[1], x[0].score), reverse=True)
    stories = group_stories(kept, key=lambda x: (x[0].title, x[1]))

    return [
        Article(
            id=i,
            title=item.title,
            url=item.url,
            source=_source(item.url),
            published_date=d,
            content=item.content,
            is_today_or_yesterday=is_recent(d),
            also=[SourceRef(title=o.title, url=o.url, source=_source(o.url)) for o, _ in others],
        )
        for i, ((item, d), *others) in enumerate(stories[:max_articles], start=1)
    ]
