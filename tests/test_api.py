import json

import pytest
from fastapi.testclient import TestClient

from app import trace
from app.api import app, get_db_path, get_runner
from app.schemas import Article, CardOut, SummaryOut


def article(i=1):
    return Article(
        id=i, title=f"title {i}", url=f"https://s.com/{i}", source="s.com",
        published_date="2026-10-29", content="body", is_today_or_yesterday=True,
    )


def card_out(i=1):
    return CardOut(
        article_id=i, relevant=True, summary="s", sentiment="negative", level="high",
        reason="r", horizon="short", title=f"title {i}", url=f"https://s.com/{i}",
        source="s.com", published_date="2026-10-29",
    )


OK = {
    "status": "ok", "message": None,
    "summary": [SummaryOut(text="point", sources=["https://s.com/1"])],
    "cards": [card_out()], "articles": [article()],
}
NO_NEWS = {"status": "no_news", "message": "No relevant news found", "summary": [], "cards": [], "articles": []}
ERROR = {"status": "error", "message": "Search is not available right now.", "summary": [], "cards": [], "articles": []}


@pytest.fixture
def client(tmp_path):
    state = {"result": OK, "calls": []}

    def fake_runner(question, topic):
        state["calls"].append((question, topic))
        return state["result"]

    app.dependency_overrides[get_runner] = lambda: fake_runner
    app.dependency_overrides[get_db_path] = lambda: str(tmp_path / "api.db")
    with TestClient(app) as c:
        c.state = state
        yield c
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ask_returns_result_and_saves_it(client):
    r = client.post("/ask", json={"question": "q", "topic": "policy"})
    assert r.status_code == 200
    body = r.json()
    assert body["query_id"] == 1 and body["status"] == "ok"
    assert body["summary"][0]["sources"] == ["https://s.com/1"]
    assert body["cards"][0]["url"] == "https://s.com/1"
    assert client.state["calls"] == [("q", "policy")]
    assert client.get("/history/1").json() == body


@pytest.mark.parametrize("result", [NO_NEWS, ERROR])
def test_no_news_and_error_are_http_200_and_saved(client, result):
    client.state["result"] = result
    r = client.post("/ask", json={"question": "q"})
    assert r.status_code == 200 and r.json()["status"] == result["status"]
    assert client.get("/history").json()[0]["status"] == result["status"]


def test_history_newest_first_and_limit(client):
    for i in range(3):
        client.post("/ask", json={"question": f"q{i}"})
    items = client.get("/history?limit=2").json()
    assert [i["question"] for i in items] == ["q2", "q1"]
    assert set(items[0]) == {"query_id", "question", "status", "created_at"}


def test_history_limit_bounds(client):
    assert client.get("/history?limit=0").status_code == 422
    assert client.get("/history?limit=101").status_code == 422


def test_history_missing_id_is_404(client):
    assert client.get("/history/999").status_code == 404


@pytest.mark.parametrize("body", [
    {"question": ""},
    {"question": "   "},
    {"question": "x" * 501},
    {"question": "q", "topic": "weather"},
])
def test_invalid_requests_are_422_and_not_run(client, body):
    assert client.post("/ask", json=body).status_code == 422
    assert client.state["calls"] == []


def test_save_failure_is_500(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr("app.api.save_run", boom)
    assert client.post("/ask", json={"question": "q"}).status_code == 500


def stream_lines(client):
    r = client.post("/ask/stream", json={"question": "q"})
    assert r.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(x) for x in r.text.splitlines() if x]


def test_ask_stream_sends_events_then_the_saved_result(client):
    def runner(question, topic):
        trace.emit("query_builder", "done", "2 queries ready")
        return OK

    app.dependency_overrides[get_runner] = lambda: runner
    lines = stream_lines(client)
    assert lines[0]["type"] == "event" and lines[0]["event"]["message"] == "2 queries ready"
    assert lines[-1]["type"] == "result" and lines[-1]["data"]["query_id"] == 1
    assert client.get("/history/1").json() == lines[-1]["data"]


def test_ask_stream_crash_becomes_an_error_line(client):
    def runner(*a):
        raise RuntimeError("boom")

    app.dependency_overrides[get_runner] = lambda: runner
    assert stream_lines(client) == [{"type": "error", "message": "Something went wrong. Please try again."}]


def test_ask_stream_save_failure_becomes_an_error_line(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr("app.api.save_run", boom)
    assert stream_lines(client)[-1] == {"type": "error", "message": "Could not save the result."}


def test_trends_endpoint(client):
    client.post("/ask", json={"question": "q"})
    body = client.get("/trends", params={"days": 7}).json()
    assert body["days"] == 7 and len(body["daily"]) == 7
    assert client.get("/trends", params={"days": 3}).status_code == 422
