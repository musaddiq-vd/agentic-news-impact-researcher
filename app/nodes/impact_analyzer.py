"""Build one impact card per article with the LLM."""

import logging

from pydantic import BaseModel, Field, model_validator

from app.config import get_settings
from app.llm import get_llm
from app.prompts import IMPACT_SYSTEM, IMPACT_USER
from app.schemas import Article, Horizon, ImpactCard, Level, Sentiment

log = logging.getLogger(__name__)
MAX_CONTENT_CHARS = 3000
MAX_CONCURRENCY = 8
RETRIES = 2


class ImpactOutput(BaseModel):
    """What the LLM returns; article_id is added by code, never by the LLM."""

    # Field order matters: the model writes fields in order, so it reasons before deciding.
    summary: str = Field(description="1-2 sentences of what the article says")
    reason: str = Field(description="one short sentence on how the article affects the business, based only on the article")
    relevant: bool = Field(description="false if the reason says the article does not address the business; true only if it can affect the business")
    sentiment: Sentiment = Field(description="positive, negative or neutral for the business")
    level: Level = Field(description="impact level: high, medium or low")
    horizon: Horizon = Field(description="short or long term")

    @model_validator(mode="before")
    @classmethod
    def _fill_irrelevant(cls, data):
        """Small models often skip fields on irrelevant articles; those cards are dropped later."""
        if isinstance(data, dict) and data.get("relevant") is False:
            data = {"sentiment": "neutral", "level": "low", "horizon": "long", **data}
        return data


def _messages(question: str, article: Article) -> list[tuple[str, str]]:
    user = IMPACT_USER.format(
        question=question,
        title=article.title,
        date=article.published_date.isoformat(),
        content=article.content[:MAX_CONTENT_CHARS],
    )
    return [("system", IMPACT_SYSTEM), ("user", user)]


def analyze_impacts(question: str, articles: list[Article], llm=None) -> list[ImpactCard]:
    """Return a card per article. Failed articles are retried once, then dropped."""
    if not articles:
        return []
    llm = llm or get_llm(get_settings().model_impact)
    chain = llm.with_structured_output(ImpactOutput)
    config = {"max_concurrency": MAX_CONCURRENCY}

    results: dict[int, ImpactOutput] = {}
    pending = list(range(len(articles)))
    for _ in range(RETRIES + 1):
        if not pending:
            break
        outputs = chain.batch(
            [_messages(question, articles[i]) for i in pending],
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
