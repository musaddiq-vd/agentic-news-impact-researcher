import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.api import app, get_db_path, get_followup_answerer, get_runner
from app.db import get_run, init_db, list_runs, save_run
from app.nodes.followup import FollowupOutput, answer_followup
from app.schemas import Article, AskResponse, CardOut, SummaryOut


def card(i):
    return CardOut(article_id=i, relevant=True, summary=f"Says {i}.", sentiment="negative", level="high",
                   reason=f"Reason {i}.", horizon="short", evidence=f"Quote {i}", title=f"Title {i}",
                   url=f"https://s.com/{i}", source="s.com", published_date="2026-11-02")


RUN = AskResponse(query_id=1, question="coal?", status="ok", cards=[card(1), card(2)])


class FakeLLM:
    def __init__(self, out):
        self.out, self.messages = out, None

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        self.messages = messages
        return self.out


def test_answer_maps_ids_to_urls_and_drops_unknown_ids():
    llm = FakeLLM(FollowupOutput(source_ids=[2, 9, 2], answer="  Review supplier contracts [2].  "))
    out = answer_followup(RUN, "ispe kya karna chahiye?", llm=llm)
    assert out == {"answer": "Review supplier contracts [2].", "sources": ["https://s.com/2"], "grounded": True}
    user = llm.messages[1][1]
    assert "[1] Title 1" in user and 'Quote: "Quote 2"' in user and "Reason 2." in user
    assert "coal?" in user and "ispe kya karna chahiye?" in user
    assert "https://" not in user  # the LLM never sees URLs


def test_answer_without_sources_is_not_grounded():
    out = answer_followup(RUN, "q", llm=FakeLLM(FollowupOutput(source_ids=[], answer="The news does not say.")))
    assert out["grounded"] is False and out["sources"] == []


# --- API ---

OK = {"status": "ok", "message": None, "summary": [SummaryOut(text="p", sources=["https://s.com/1"])],
      "cards": [card(1)], "articles": [Article(id=1, title="Title 1", url="https://s.com/1", source="s.com",
                                               published_date="2026-11-02", content="c", is_today_or_yesterday=True)]}


@pytest.fixture
def client(tmp_path):
    seen = []

    def answerer(run, question):
        seen.append((run, question))
        return {"answer": f"About {question}", "sources": ["https://s.com/1"], "grounded": True}

    app.dependency_overrides[get_runner] = lambda: (lambda q, t: OK)
    app.dependency_overrides[get_followup_answerer] = lambda: answerer
    app.dependency_overrides[get_db_path] = lambda: str(tmp_path / "f.db")
    with TestClient(app) as c:
        c.seen = seen
        yield c
    app.dependency_overrides.clear()


def test_followup_is_answered_saved_and_shown_in_history(client):
    qid = client.post("/ask", json={"question": "coal?"}).json()["query_id"]
    r = client.post("/followup", json={"query_id": qid, "question": "what now?"})
    assert r.status_code == 200 and r.json()["answer"] == "About what now?"
    client.post("/followup", json={"query_id": qid, "question": "and later?"})
    # the second call sees the first follow-up as context
    assert [f.question for f in client.seen[1][0].followups] == ["what now?"]
    run = client.get(f"/history/{qid}").json()
    assert run["question"] == "coal?" and [f["question"] for f in run["followups"]] == ["what now?", "and later?"]


def test_followup_errors(client):
    assert client.post("/followup", json={"query_id": 99, "question": "x"}).status_code == 404
    assert client.post("/followup", json={"query_id": 1, "question": ""}).status_code == 422
    app.dependency_overrides[get_runner] = lambda: (lambda q, t: {**OK, "status": "no_news", "cards": [], "articles": [], "summary": []})
    qid = client.post("/ask", json={"question": "x"}).json()["query_id"]
    assert client.post("/followup", json={"query_id": qid, "question": "x"}).status_code == 409


def test_followup_llm_failure_is_502(client):
    qid = client.post("/ask", json={"question": "coal?"}).json()["query_id"]

    def boom(run, q):
        raise RuntimeError("bedrock down")

    app.dependency_overrides[get_followup_answerer] = lambda: boom
    r = client.post("/followup", json={"query_id": qid, "question": "x"})
    assert r.status_code == 502 and "try again" in r.json()["detail"]


# --- DB migration ---

def test_old_db_with_competitors_column_still_works(tmp_path):
    db = str(tmp_path / "old.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE queries (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, topic TEXT,"
        " competitors TEXT NOT NULL, status TEXT NOT NULL, message TEXT, summary_json TEXT NOT NULL,"
        " created_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO queries (question, topic, competitors, status, message, summary_json, created_at)"
                 " VALUES ('old q', NULL, '[]', 'no_news', NULL, '[]', '2026-10-01T10:00:00+05:30')")
    conn.commit()
    conn.close()

    init_db(db)
    cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(queries)")]
    assert "competitors" not in cols
    assert list_runs(path=db)[0]["question"] == "old q"
    qid = save_run("new q", None, OK, path=db)
    assert get_run(qid, path=db).question == "new q"
