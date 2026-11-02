"""FastAPI app. This is the only place that saves runs to the DB."""

import json
import logging
import queue
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from app import trace
from app.config import IST
from app.db import get_run, init_db, list_impacts, list_runs, save_followup, save_run
from app.graph import run_graph
from app.nodes.followup import answer_followup
from app.schemas import AskRequest, AskResponse, FollowupOut, FollowupRequest, HistoryItem
from app.trends import build_trends

log = logging.getLogger(__name__)


def get_runner():
    """The function that answers a question; tests override it with a fake."""
    return run_graph


def get_followup_answerer():
    """The function that answers follow-ups; tests override it with a fake."""
    return answer_followup


def get_db_path() -> str | None:
    """None means the DB_PATH from settings; tests override it with a temp file."""
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(app.dependency_overrides.get(get_db_path, get_db_path)())
    yield


app = FastAPI(title="Agentic AI News Impact System", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _save(req: AskRequest, result: dict, db_path: str | None) -> AskResponse:
    try:
        query_id = save_run(req.question, req.topic, result, path=db_path)
    except Exception:
        log.exception("could not save the run")
        raise HTTPException(status_code=500, detail="Could not save the result.")
    return AskResponse(
        query_id=query_id,
        question=req.question,
        status=result["status"],
        message=result["message"],
        summary=result["summary"],
        cards=result["cards"],
    )


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, runner=Depends(get_runner), db_path=Depends(get_db_path)) -> AskResponse:
    """Run the graph, save the result, return it. ok, no_news and error all return HTTP 200."""
    return _save(req, runner(req.question, req.topic), db_path)


@app.post("/ask/stream")
def ask_stream(req: AskRequest, runner=Depends(get_runner), db_path=Depends(get_db_path)) -> StreamingResponse:
    """Like /ask, but streams NDJSON while the agents work: one {"type": "event"} line per
    agent event, then a single {"type": "result", "data": AskResponse} or {"type": "error"} line."""
    lines: queue.Queue = queue.Queue()
    end = object()

    def work() -> None:
        try:
            with trace.listen(lambda ev: lines.put({"type": "event", "event": ev})):
                result = runner(req.question, req.topic)
            lines.put({"type": "result", "data": _save(req, result, db_path).model_dump(mode="json")})
        except HTTPException as exc:
            lines.put({"type": "error", "message": exc.detail})
        except Exception:
            log.exception("streamed run failed")
            lines.put({"type": "error", "message": "Something went wrong. Please try again."})
        finally:
            lines.put(end)

    threading.Thread(target=work, daemon=True).start()

    def body():
        while (item := lines.get()) is not end:
            yield json.dumps(item, default=str) + "\n"

    return StreamingResponse(body(), media_type="application/x-ndjson")


@app.get("/history", response_model=list[HistoryItem])
def history(limit: int = Query(20, ge=1, le=100), db_path=Depends(get_db_path)) -> list[dict]:
    return list_runs(limit, path=db_path)


@app.get("/history/{query_id}", response_model=AskResponse)
def history_item(query_id: int, db_path=Depends(get_db_path)) -> AskResponse:
    run = get_run(query_id, path=db_path)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@app.get("/trends")
def trends(days: int = Query(30, ge=7, le=90), db_path=Depends(get_db_path)) -> dict:
    """Sentiment trends of the saved news, by day and by theme, for the last `days` days."""
    today = datetime.now(IST).date()
    since = (today - timedelta(days=days - 1)).isoformat()
    return build_trends(list_impacts(since, path=db_path), days, today)


@app.post("/followup", response_model=FollowupOut)
def followup(
    req: FollowupRequest, answerer=Depends(get_followup_answerer), db_path=Depends(get_db_path),
) -> FollowupOut:
    """Answer a follow-up about a saved run, using only that run's news cards, and save it."""
    run = get_run(req.query_id, path=db_path)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if not run.cards:
        raise HTTPException(status_code=409, detail="This answer has no news to ask about.")
    try:
        answer = answerer(run, req.question)
    except Exception:
        log.exception("follow-up failed")
        raise HTTPException(status_code=502, detail="Could not answer the follow-up. Please try again.")
    return save_followup(req.query_id, req.question, answer, path=db_path)
