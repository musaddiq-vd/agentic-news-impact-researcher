import json
from contextlib import contextmanager
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


EVENTS = [
    {"agent": "query_builder", "event": "start", "message": "turning the question into search queries", "t": 0.0},
    {"agent": "query_builder", "event": "done", "message": "2 queries ready", "t": 0.5, "ms": 500},
    {"agent": "search_1", "event": "done", "message": "5 articles found", "t": 1.0, "ms": 400},
]


class FakeApi:
    """Replaces httpx.request and httpx.stream; routes by method and path."""

    def __init__(self, ask=None, history=None, runs=None, error=None, trends=None, events=EVENTS):
        self.ask, self.history, self.runs, self.error = ask, history or [], runs or {}, error
        self.trends, self.events = trends, events
        self.calls = []

    @contextmanager
    def stream(self, method, url, **kw):
        """/ask/stream: the scripted events as NDJSON, then the result line."""
        self.calls.append((method, url, kw.get("json")))
        if self.error:
            raise self.error
        if isinstance(self.ask, httpx.Response):
            yield self.ask
            return
        lines = [{"type": "event", "event": ev} for ev in self.events] + [{"type": "result", "data": self.ask}]
        body = "".join(json.dumps(line) + "\n" for line in lines).encode()
        yield httpx.Response(200, content=body, request=httpx.Request(method, url))

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
        if path == "/trends":
            return httpx.Response(200, json=self.trends, request=req)
        if path == "/followup":
            q = kw["json"]["question"]
            return httpx.Response(200, request=req, json={
                "question": q, "answer": f"Idea: watch tariffs ({q})", "sources": ["https://s.com/1"],
                "grounded": True, "created_at": "2026-11-03T09:00:00+05:30",
            })
        qid = int(path.rsplit("/", 1)[1])
        if qid in self.runs:
            return httpx.Response(200, json=self.runs[qid], request=req)
        return httpx.Response(404, json={"detail": "x"}, request=req)


def run_ask(monkeypatch, api, question="How do tariffs affect me?"):
    monkeypatch.setattr(httpx, "request", api)
    monkeypatch.setattr(httpx, "stream", api.stream)
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
    assert api.calls[0][2] == {"question": "How do tariffs affect me?", "topic": "any"}


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


def test_there_is_no_competitor_filter(monkeypatch):
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


def test_live_agent_board_shows_streamed_events(monkeypatch):
    at = run_ask(monkeypatch, FakeApi(ask=result()))
    md = texts(at.markdown)
    assert "2 queries ready" in md and "5 articles found" in md      # board + feed
    assert "pipe-step done" in md and "Search agent 2" in md
    assert "Rules changed." in md                                    # result still shown


def test_stream_error_line_is_shown(monkeypatch):
    api = FakeApi(ask=result())

    @contextmanager
    def stream(method, url, **kw):
        body = json.dumps({"type": "error", "message": "Could not save the result."}) + "\n"
        yield httpx.Response(200, content=body.encode(), request=httpx.Request(method, url))

    api.stream = stream
    at = run_ask(monkeypatch, api)
    assert at.error[0].value == "Could not save the result."


TRENDS = {
    "days": 30, "total": 3,
    "overall": {"positive": 1, "negative": 2, "neutral": 0, "score": -33,
                "earlier_score": 100, "recent_score": -100, "direction": "worse"},
    "daily": [{"date": (TODAY - timedelta(days=i)).isoformat(), "positive": 0, "negative": i % 2, "neutral": 0}
              for i in range(29, -1, -1)],
    "themes": [{"theme": "Coal", "count": 3, "positive": 1, "negative": 2, "neutral": 0, "score": -33,
                "earlier_score": 100, "recent_score": -100, "direction": "worse",
                "latest": {"title": "Coal hits high", "url": "https://s.com/c", "sentiment": "negative",
                           "published_date": TODAY.isoformat()}}],
    "highlights": ["Coal news is turning more negative (+100 → -100)"],
}


def open_trends(monkeypatch, api):
    monkeypatch.setattr(httpx, "request", api)
    at = AppTest.from_file(APP, default_timeout=15).run()
    at.sidebar.radio[0].set_value("Trends").run()
    return at


def test_trends_page_shows_mood_highlights_and_themes(monkeypatch):
    at = open_trends(monkeypatch, FakeApi(trends=TRENDS))
    assert not at.exception
    md = texts(at.markdown)
    assert "-33" in md and "Negative" in md                         # mood card
    assert "Coal news is turning more negative" in md               # highlight
    assert "Coal hits high" in md and "Getting worse" in md         # theme card
    assert [m.value for m in at.metric] == ["3", "1", "2", "0"]


def test_follow_up_idea_is_asked_and_answered(monkeypatch):
    api = FakeApi(ask=result())
    at = run_ask(monkeypatch, api)
    assert "Ask a follow-up" in texts(at.subheader)
    fu_pills = next(b for b in at.button_group if "Ispe mujhe kya karna chahiye?" in b.options)
    fu_pills.set_value("Ispe mujhe kya karna chahiye?").run()
    assert api.calls[-1][2] == {"query_id": 1, "question": "Ispe mujhe kya karna chahiye?"}
    md = texts(at.markdown)
    assert "Idea: watch tariffs" in md and "[[s.com]](https://s.com/1)" in md
    assert not at.exception


def test_saved_follow_ups_show_in_history(monkeypatch):
    run = {**result(), "followups": [{"question": "Old follow-up", "answer": "Old answer", "sources": [],
                                      "grounded": False, "created_at": "2026-11-01T10:00:00+05:30"}]}
    api = FakeApi(history=[{"query_id": 1, "question": "Q", "status": "ok", "created_at": "2026-11-01T09:00:00+05:30"}],
                  runs={1: run})
    monkeypatch.setattr(httpx, "request", api)
    at = AppTest.from_file(APP, default_timeout=15).run()
    at.sidebar.radio[0].set_value("History").run()
    assert "Old answer" in texts(at.markdown)
    assert any("Not backed by the news" in c.value for c in at.caption)


def test_trends_page_without_data(monkeypatch):
    empty = {**TRENDS, "total": 0, "themes": [], "highlights": []}
    at = open_trends(monkeypatch, FakeApi(trends=empty))
    assert "No saved news" in at.info[0].value
