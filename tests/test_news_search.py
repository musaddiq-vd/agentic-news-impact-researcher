from datetime import datetime

import pytest

from app.config import IST
from app.nodes.news_search import SearchError, search_news

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=IST)


def result(url, title="t", date="Wed, 28 Oct 2026 10:00:00 GMT", score=0.5):
    return {"url": url, "title": title, "content": "c", "published_date": date, "score": score}


class FakeTool:
    """Returns scripted responses per call; an Exception in the script is raised."""

    def __init__(self, script):
        self.script, self.calls = list(script), []

    def invoke(self, args):
        self.calls.append(args)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return {"results": item}


def test_returns_raw_articles_and_sends_date_range():
    tool = FakeTool([[result("https://a.com/1")]])
    out = search_news(["q"], days=30, tool=tool, now=NOW)
    assert out[0].url == "https://a.com/1" and out[0].published_date
    assert tool.calls[0] == {"query": "q", "start_date": "2026-09-29", "end_date": "2026-10-29"}


def test_dedupes_urls_across_queries():
    tool = FakeTool([
        [result("https://a.com/1"), result("https://a.com/2")],
        [result("https://a.com/1/"), result("https://a.com/3")],
    ])
    out = search_news(["q1", "q2"], tool=tool, now=NOW)
    assert [a.url for a in out] == ["https://a.com/1", "https://a.com/2", "https://a.com/3"]


def test_missing_fields_get_defaults():
    tool = FakeTool([[{"url": "https://a.com/1"}]])
    a = search_news(["q"], tool=tool, now=NOW)[0]
    assert a.title == "" and a.content == "" and a.published_date is None and a.score == 0.0


def test_skips_results_without_url():
    tool = FakeTool([[{"title": "no url"}, result("https://a.com/1")]])
    assert len(search_news(["q"], tool=tool, now=NOW)) == 1


def test_retries_once_then_succeeds():
    tool = FakeTool([RuntimeError("timeout"), [result("https://a.com/1")]])
    assert len(search_news(["q"], tool=tool, now=NOW)) == 1
    assert len(tool.calls) == 2


def test_continues_when_one_query_fails():
    tool = FakeTool([RuntimeError("x"), RuntimeError("x"), [result("https://a.com/1")]])
    assert len(search_news(["bad", "good"], tool=tool, now=NOW)) == 1


def test_raises_when_all_queries_fail():
    tool = FakeTool([RuntimeError("x")] * 2)
    with pytest.raises(SearchError):
        search_news(["q"], tool=tool, now=NOW)
