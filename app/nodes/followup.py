"""Answer a follow-up question using only the cards of a saved run."""

from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm import get_llm
from app.prompts import FOLLOWUP_SYSTEM, FOLLOWUP_USER
from app.schemas import AskResponse

MAX_HISTORY = 4  # earlier follow-ups sent as context


class FollowupOutput(BaseModel):
    # Field order matters: the model picks its sources before it writes.
    source_ids: list[int] = Field(default=[], description="IDs of the news items the answer relies on")
    answer: str = Field(description="the answer, at most 120 words")


def _items(run: AskResponse) -> str:
    """Numbered items (1..n in card order): the article's words and the impact analysis. No URLs."""
    lines = []
    for i, c in enumerate(run.cards, start=1):
        quote = f'    Quote: "{c.evidence}"\n' if c.evidence else ""
        lines.append(
            f"[{i}] {c.title} ({c.published_date.isoformat()}, {c.source})\n"
            f"    Says: {c.summary}\n{quote}"
            f"    Impact: {c.sentiment}, {c.level}, {c.horizon} term. {c.reason}"
        )
    return "\n".join(lines)


def _history(run: AskResponse) -> str:
    recent = run.followups[-MAX_HISTORY:]
    return "\n".join(f"Q: {f.question}\nA: {f.answer}" for f in recent) or "none"


def answer_followup(run: AskResponse, question: str, llm=None) -> dict:
    """Return {answer, sources (URLs), grounded}.

    Unknown source IDs are dropped; code maps IDs to URLs. An answer without any valid
    source is marked not grounded so the UI can say so.
    """
    llm = llm or get_llm(get_settings().model_summary)
    chain = llm.with_structured_output(FollowupOutput)
    out = chain.invoke([
        ("system", FOLLOWUP_SYSTEM),
        ("user", FOLLOWUP_USER.format(
            question=run.question, history=_history(run), items=_items(run), followup=question,
        )),
    ])
    ids = [i for i in dict.fromkeys(out.source_ids) if 1 <= i <= len(run.cards)]
    urls = [run.cards[i - 1].url for i in ids]
    return {"answer": out.answer.strip(), "sources": urls, "grounded": bool(urls)}
