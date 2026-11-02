from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from app.config import IST
from ui.streamlit_app import age_label

APP = str(Path(__file__).resolve().parent.parent / "ui" / "streamlit_app.py")
TODAY = datetime.now(IST).date()


def card(title="Rooftop rules updated", published=TODAY, sentiment="positive"):
    return {
        "article_id": 1, "relevant": True, "summary": "Net metering rules changed.",
        "sentiment": sentiment, "level": "high", "reason": "Demand may rise.",
        "horizon": "short", "evidence": "Net metering rules were relaxed.",
        "title": title, "url": "https://s.com/1",
        "source": "s.com", "published_date": published.isoformat(),
    }


def result(status="ok", message=None, cards=None, summary=None):
    return {
        "query_id": 1, "status": status, "message": message,
        "summary": summary if summary is not None else
        [{"text": "Rules changed.", "sources": ["https://s.com/1", "https://s.com/2"]}],
        "cards": cards if cards is not None else [card()],
    }


class FakeApi:
    """Replaces httpx.request; routes by method and path."""

    def __init__(self, ask=None, history=None, runs=None, error=None):
        self.ask, self.history, self.runs, self.error = ask, history or [], runs or {}, error
        self.calls = []

    def __call__(self, method, url, **kw):
        if url.endswith("/health"):  # sidebar status check, not counted as a call
            if self.error:
                raise self.error
            return httpx.Response(200, json={"status": "ok"}, request=httpx.Request(method, url))
        self.calls.append((method, url, kw.get("json")))
        if self.error:
            raise self.error
        req = httpx.Request(method, url)
        path = url.split("8000", 1)[1]
        if path == "/ask":
            return self.ask if isinstance(self.ask, httpx.Response) else httpx.Response(200, json=self.ask, request=req)
        if path == "/history":
            return httpx.Response(200, json=self.history, request=req)
        qid = int(path.rsplit("/", 1)[1])
        if qid in self.runs:
            return httpx.Response(200, json=self.runs[qid], request=req)
        return httpx.Response(404, json={"detail": "x"}, request=req)


def run_ask(monkeypatch, api, question="How do tariffs affect me?"):
    monkeypatch.setattr(httpx, "request", api)
    at = AppTest.from_file(APP, default_timeout=15).run()
    at.text_area[0].set_value(question)
    at.button[0].click().run()
    return at


def texts(elements):
    return " ".join(e.value for e in elements)


def test_ask_page_renders_without_errors(monkeypatch):
    monkeypatch.setattr(httpx, "request", FakeApi())
    at = AppTest.from_file(APP, default_timeout=15).run()
    assert not at.exception
    assert at.title[0].value == "News Impact"
    assert at.selectbox[0].options[0] == "any"
    # Nothing may render after the form (a bare expression once printed a stray "None").
    assert [type(e).__name__ for e in at.main][-1] == "Button"


def test_ok_result_shows_summary_links_and_cards(monkeypatch):
    api = FakeApi(ask=result())
    at = run_ask(monkeypatch, api)
    md = texts(at.markdown)
    assert "Rules changed." in md and "https://s.com/2" in md        # summary + source links
    assert "[[s.com]](https://s.com/1)" in md                         # link labelled by site
    assert "[Rooftop rules updated](https://s.com/1)" in md          # card title link
    assert ":green-badge[positive]" in md and ":blue-badge[high impact]" in md
    assert ":orange-badge[Today]" in md and "**Why (analysis):** Demand may rise." in md
    assert "**From the article:** “Net metering rules were relaxed.”" in md
    assert api.calls[0][2] == {"question": "How do tariffs affect me?", "topic": "any", "competitors": []}


def test_old_news_has_no_fresh_badge_and_negative_is_red(monkeypatch):
    old = card(published=TODAY - timedelta(days=5), sentiment="negative")
    at = run_ask(monkeypatch, FakeApi(ask=result(cards=[old])))
    md = texts(at.markdown)
    assert ":red-badge[negative]" in md and "orange-badge" not in md


def test_summary_missing_shows_warning_and_cards(monkeypatch):
    at = run_ask(monkeypatch, FakeApi(ask=result(message="Summary could not be generated.", summary=[])))
    assert at.warning[0].value == "Summary could not be generated."
    assert "Rooftop rules updated" in texts(at.markdown)


def test_not_a_direct_answer_warning_is_shown_with_the_summary(monkeypatch):
    msg = "News was found, but it does not directly answer your question."
    at = run_ask(monkeypatch, FakeApi(ask=result(message=msg)))
    assert at.warning[0].value == msg
    assert "Rules changed." in texts(at.markdown) and "Rooftop rules updated" in texts(at.markdown)


def test_no_news_shows_info(monkeypatch):
    at = run_ask(monkeypatch, FakeApi(ask=result("no_news", "No relevant news found.", [], [])))
    assert at.info[0].value == "No relevant news found."


def test_error_status_shows_error(monkeypatch):
    at = run_ask(monkeypatch, FakeApi(ask=result("error", "Search is not available right now.", [], [])))
    assert at.error[0].value == "Search is not available right now."


def test_api_down_shows_friendly_error(monkeypatch):
    at = run_ask(monkeypatch, FakeApi(error=httpx.ConnectError("refused")))
    assert "API is not running" in at.error[0].value


def test_invalid_input_shows_friendly_error(monkeypatch):
    bad = httpx.Response(422, json={"detail": []}, request=httpx.Request("POST", "http://x/ask"))
    at = run_ask(monkeypatch, FakeApi(ask=bad))
    assert "Invalid input" in at.error[0].value


def test_empty_question_does_not_call_api(monkeypatch):
    api = FakeApi(ask=result())
    at = run_ask(monkeypatch, api, question="   ")
    assert at.warning[0].value == "Please type a question."
    assert api.calls == []


def test_dollar_sign_is_escaped(monkeypatch):
    c = card()
    c["summary"] = "Costs $5 and $6."
    at = run_ask(monkeypatch, FakeApi(ask=result(cards=[c])))
    assert "Costs \\$5 and \\$6." in texts(at.markdown)


def test_history_page_lists_and_opens_a_run(monkeypatch):
    api = FakeApi(
        history=[{"query_id": 7, "question": "Old question", "status": "ok", "created_at": "2026-10-29T19:30:59+05:30"}],
        runs={7: result()},
    )
    monkeypatch.setattr(httpx, "request", api)
    at = AppTest.from_file(APP, default_timeout=15).run()
    at.sidebar.radio[0].set_value("History").run()
    assert "Old question" in at.selectbox[0].options[0]
    assert "Rules changed." in texts(at.markdown)


def test_history_empty_and_api_down(monkeypatch):
    monkeypatch.setattr(httpx, "request", FakeApi(history=[]))
    at = AppTest.from_file(APP, default_timeout=15).run()
    at.sidebar.radio[0].set_value("History").run()
    assert at.info[0].value == "No questions yet."

    monkeypatch.setattr(httpx, "request", FakeApi(error=httpx.ConnectError("x")))
    at = AppTest.from_file(APP, default_timeout=15).run()
    at.sidebar.radio[0].set_value("History").run()
    assert "API is not running" in at.error[0].value


@pytest.mark.parametrize("days,label", [(0, "Today"), (1, "Yesterday"), (2, None), (30, None)])
def test_age_label(days, label):
    today = date(2026, 10, 29)
    assert age_label(today - timedelta(days=days), today) == label


def test_competitor_filter_is_not_shown(monkeypatch):
    monkeypatch.setattr(httpx, "request", FakeApi())
    at = AppTest.from_file(APP, default_timeout=15).run()
    assert not at.multiselect
    assert "competitor" not in at.selectbox[0].options


def test_metrics_and_sentiment_filter(monkeypatch):
    cards = [card(title="Good news"), card(title="Bad news", sentiment="negative")]
    at = run_ask(monkeypatch, FakeApi(ask=result(cards=cards)))
    assert [m.value for m in at.metric] == ["2", "1", "1", "2"]
    at.button_group[1].set_value(["negative"]).run()  # [0] is the example pills
    md = texts(at.markdown)
    assert "Bad news" in md and "Good news" not in md


def test_history_ask_again_prefills_question(monkeypatch):
    api = FakeApi(
        history=[{"query_id": 7, "question": "Old question", "status": "ok", "created_at": "2026-10-29T19:30:59+05:30"}],
        runs={7: result()},
    )
    monkeypatch.setattr(httpx, "request", api)
    at = AppTest.from_file(APP, default_timeout=15).run()
    at.sidebar.radio[0].set_value("History").run()
    next(b for b in at.button if "Ask again" in b.label).click().run()
    assert at.text_area[0].value == "Old question"
