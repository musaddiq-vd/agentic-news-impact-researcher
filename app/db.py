"""SQLite storage: queries, articles, impacts. Only api.py calls save_run."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime

from app.config import IST, get_settings
from app.schemas import AskResponse, CardOut, FollowupOut, SourceRef, SummaryOut

SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    topic TEXT,
    status TEXT NOT NULL,
    message TEXT,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER NOT NULL REFERENCES queries(id),
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    published_date TEXT NOT NULL,
    content TEXT NOT NULL,
    rank INTEGER NOT NULL,
    also_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS impacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES articles(id),
    relevant INTEGER NOT NULL,
    summary TEXT NOT NULL,
    sentiment TEXT NOT NULL,
    level TEXT NOT NULL,
    reason TEXT NOT NULL,
    horizon TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER NOT NULL REFERENCES queries(id),
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    grounded INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _connect(path: str | None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or get_settings().db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | None = None) -> None:
    """Create the tables if they do not exist, and add columns missing from older DBs."""
    with closing(_connect(path)) as conn, conn:
        conn.executescript(SCHEMA)
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(impacts)")}
        if "also_json" not in {r["name"] for r in conn.execute("PRAGMA table_info(articles)")}:
            conn.execute("ALTER TABLE articles ADD COLUMN also_json TEXT NOT NULL DEFAULT '[]'")
        if "evidence" not in columns:
            conn.execute("ALTER TABLE impacts ADD COLUMN evidence TEXT NOT NULL DEFAULT ''")
        # The competitor filter was removed; old DBs still have its NOT NULL column.
        if "competitors" in {r["name"] for r in conn.execute("PRAGMA table_info(queries)")}:
            conn.execute("ALTER TABLE queries DROP COLUMN competitors")


def save_run(
    question: str,
    topic: str | None,
    result: dict,
    path: str | None = None,
) -> int:
    """Save one run (all-or-nothing) and return its query_id.

    `result` is the dict from run_graph. Article rank equals the graph's article id.
    """
    init_db(path)
    with closing(_connect(path)) as conn, conn:
        cur = conn.execute(
            "INSERT INTO queries (question, topic, status, message, summary_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                question,
                topic,
                result["status"],
                result["message"],
                json.dumps([s.model_dump() for s in result["summary"]]),
                datetime.now(IST).isoformat(timespec="seconds"),
            ),
        )
        query_id = cur.lastrowid

        db_ids: dict[int, int] = {}
        for a in result["articles"]:
            c = conn.execute(
                "INSERT INTO articles (query_id, title, url, source, published_date, content, rank, also_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (query_id, a.title, a.url, a.source, a.published_date.isoformat(), a.content, a.id,
                 json.dumps([s.model_dump() for s in a.also])),
            )
            db_ids[a.id] = c.lastrowid

        for card in result["cards"]:
            conn.execute(
                "INSERT INTO impacts (article_id, relevant, summary, sentiment, level, reason, horizon, evidence)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    db_ids[card.article_id],  # KeyError rolls the whole save back
                    int(card.relevant),
                    card.summary,
                    card.sentiment,
                    card.level,
                    card.reason,
                    card.horizon,
                    card.evidence,
                ),
            )
    return query_id


def list_runs(limit: int = 20, path: str | None = None) -> list[dict]:
    """Newest runs first: query_id, question, status, created_at."""
    init_db(path)
    with closing(_connect(path)) as conn:
        rows = conn.execute(
            "SELECT id, question, status, created_at FROM queries ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {"query_id": r["id"], "question": r["question"], "status": r["status"], "created_at": r["created_at"]}
        for r in rows
    ]


def get_run(query_id: int, path: str | None = None) -> AskResponse | None:
    """Rebuild the saved response, or None if the id does not exist."""
    init_db(path)
    with closing(_connect(path)) as conn:
        q = conn.execute("SELECT * FROM queries WHERE id = ?", (query_id,)).fetchone()
        if q is None:
            return None
        rows = conn.execute(
            "SELECT a.rank, a.title, a.url, a.source, a.published_date, a.also_json,"
            " i.relevant, i.summary, i.sentiment, i.level, i.reason, i.horizon, i.evidence"
            " FROM impacts i JOIN articles a ON a.id = i.article_id"
            " WHERE a.query_id = ? ORDER BY a.rank",
            (query_id,),
        ).fetchall()
        followups = conn.execute(
            "SELECT * FROM followups WHERE query_id = ? ORDER BY id", (query_id,)
        ).fetchall()
    return AskResponse(
        query_id=query_id,
        question=q["question"],
        status=q["status"],
        message=q["message"],
        summary=[SummaryOut(**s) for s in json.loads(q["summary_json"])],
        cards=[
            CardOut(
                article_id=r["rank"],
                relevant=bool(r["relevant"]),
                summary=r["summary"],
                sentiment=r["sentiment"],
                level=r["level"],
                reason=r["reason"],
                horizon=r["horizon"],
                evidence=r["evidence"],
                title=r["title"],
                url=r["url"],
                source=r["source"],
                published_date=r["published_date"],
                also_reported_by=[SourceRef(**s) for s in json.loads(r["also_json"])],
            )
            for r in rows
        ],
        followups=[
            FollowupOut(
                question=f["question"], answer=f["answer"], sources=json.loads(f["sources_json"]),
                grounded=bool(f["grounded"]), created_at=f["created_at"],
            )
            for f in followups
        ],
    )


def save_followup(query_id: int, question: str, answer: dict, path: str | None = None) -> FollowupOut:
    """Save one follow-up answer ({answer, sources, grounded}) and return it."""
    init_db(path)
    out = FollowupOut(question=question, created_at=datetime.now(IST).isoformat(timespec="seconds"), **answer)
    with closing(_connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO followups (query_id, question, answer, sources_json, grounded, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (query_id, out.question, out.answer, json.dumps(out.sources), int(out.grounded), out.created_at),
        )
    return out


def list_impacts(since: str, path: str | None = None) -> list[dict]:
    """Relevant saved impact cards for news published on or after `since` (ISO date).

    The same article can be saved by several runs; only its newest analysis is kept.
    """
    init_db(path)
    with closing(_connect(path)) as conn:
        rows = conn.execute(
            "SELECT a.title, a.url, a.source, a.published_date, i.summary, i.sentiment, i.level, i.horizon"
            " FROM impacts i JOIN articles a ON a.id = i.article_id"
            " WHERE i.relevant = 1 AND a.published_date >= ? ORDER BY i.id DESC",
            (since,),
        ).fetchall()
    seen: set[str] = set()
    out = []
    for r in rows:
        key = r["url"].rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            out.append(dict(r))
    return out
