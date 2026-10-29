"""Build one impact card per article with the LLM."""

import logging
import time

from pydantic import BaseModel, Field, model_validator

from app.config import get_settings
from app.llm import get_llm
from app.prompts import IMPACT_SYSTEM, IMPACT_USER
from app.schemas import Article, Horizon, ImpactCard, Level, Sentiment

log = logging.getLogger(__name__)
MAX_CONTENT_CHARS = 3000
MAX_CONCURRENCY = 3  # 8 parallel calls hit Bedrock throttling with Nova Pro
RETRIES = 2
RETRY_DELAY_SECONDS = 3.0  # wait before retrying failed articles (throttling needs a pause)


class ImpactOutput(BaseModel):
    """What the LLM returns; article_id is added by code, never by the LLM."""

    # Field order matters: the model writes fields in order, so it quotes and reasons before deciding.
    evidence: str = Field(
        default="",
        description="one short passage (max 30 words) copied word for word from the article text "
        "that shows the link to the business; empty if there is none",
    )
    summary: str = Field(description="1-2 sentences of what the article itself says")
    reason: str = Field(description="one short sentence on how the evidence could affect the business")
    relevant: bool = Field(description="false if the evidence is empty; true only if the evidence shows the article can affect the business")
    sentiment: Sentiment = Field(description="positive, negative or neutral for the business")
    level: Level = Field(description="impact level: high, medium or low")
    horizon: Horizon = Field(description="short or long term")

    @model_validator(mode="before")
    @classmethod
    def _fill_irrelevant(cls, data):
        """Models sometimes skip fields. Irrelevant cards are dropped later anyway; a relevant
        card without a level gets the most cautious one ("low") instead of being lost."""
        if isinstance(data, dict):
            if data.get("relevant") is False:
                data = {"sentiment": "neutral", "level": "low", "horizon": "long", **data}
            elif "level" not in data:
                data = {**data, "level": "low"}
        return data


def _messages(article: Article) -> list[tuple[str, str]]:
    # The user's question is not sent on purpose: with it, the model tied every
    # article to the question ("... which can affect module production cost").
    user = IMPACT_USER.format(
        title=article.title,
        date=article.published_date.isoformat(),
        content=article.content[:MAX_CONTENT_CHARS],
    )
    return [("system", IMPACT_SYSTEM), ("user", user)]


def analyze_impacts(question: str, articles: list[Article], llm=None) -> list[ImpactCard]:
    """Return a card per article. Failed articles are retried up to RETRIES times, then dropped.

    `question` is kept in the signature for the graph but is not sent to the model.
    """
    if not articles:
        return []
    llm = llm or get_llm(get_settings().model_impact)
    chain = llm.with_structured_output(ImpactOutput)
    config = {"max_concurrency": MAX_CONCURRENCY}

    results: dict[int, ImpactOutput] = {}
    pending = list(range(len(articles)))
    for attempt in range(RETRIES + 1):
        if not pending:
            break
        if attempt:
            time.sleep(RETRY_DELAY_SECONDS * attempt)
        outputs = chain.batch(
            [_messages(articles[i]) for i in pending],
            config=config,
            return_exceptions=True,
        )
        still_failing = []
        for i, out in zip(pending, outputs):
            if isinstance(out, ImpactOutput):
                results[i] = out
            else:
                still_failing.append(i)
                log.warning("impact failed for article %s: %s", articles[i].id, out)
        pending = still_failing

    return [
        ImpactCard(article_id=articles[i].id, **results[i].model_dump())
        for i in sorted(results)
    ]
