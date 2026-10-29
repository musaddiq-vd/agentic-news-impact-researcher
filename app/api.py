"""FastAPI app. This is the only place that saves runs to the DB."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query

from app.db import get_run, init_db, list_runs, save_run
from app.graph import run_graph
from app.schemas import AskRequest, AskResponse, HistoryItem

log = logging.getLogger(__name__)


def get_runner():
    """The function that answers a question; tests override it with a fake."""
    return run_graph


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


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, runner=Depends(get_runner), db_path=Depends(get_db_path)) -> AskResponse:
    """Run the graph, save the result, return it. ok, no_news and error all return HTTP 200."""
    result = runner(req.question, req.topic, req.competitors)
    try:
        query_id = save_run(req.question, req.topic, req.competitors, result, path=db_path)
    except Exception:
        log.exception("could not save the run")
        raise HTTPException(status_code=500, detail="Could not save the result.")
    return AskResponse(
        query_id=query_id,
        status=result["status"],
        message=result["message"],
        summary=result["summary"],
        cards=result["cards"],
    )


@app.get("/history", response_model=list[HistoryItem])
def history(limit: int = Query(20, ge=1, le=100), db_path=Depends(get_db_path)) -> list[dict]:
    return list_runs(limit, path=db_path)


@app.get("/history/{query_id}", response_model=AskResponse)
def history_item(query_id: int, db_path=Depends(get_db_path)) -> AskResponse:
    run = get_run(query_id, path=db_path)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run
