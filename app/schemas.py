"""Data models (PLAN.md section 1)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Sentiment = Literal["positive", "negative", "neutral"]
Level = Literal["high", "medium", "low"]
Horizon = Literal["short", "long"]
Status = Literal["ok", "no_news", "error"]


class RawArticle(BaseModel):
    """One Tavily result, unmodified."""

    title: str
    url: str
    content: str
    published_date: str | None = None
    score: float = 0.0


class Article(BaseModel):
    """Article after filtering and ranking."""

    id: int
    title: str
    url: str
    source: str
    published_date: date
    content: str
    is_today_or_yesterday: bool


class ImpactCard(BaseModel):
    """LLM output: business impact of one article. The LLM never returns URLs."""

    article_id: int
    relevant: bool
    summary: str
    sentiment: Sentiment
    level: Level
    reason: str
    horizon: Horizon


class SummaryPoint(BaseModel):
    """LLM summary point: article IDs only; code adds the URLs."""

    text: str
    source_ids: list[int] = Field(min_length=1)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    topic: str | None = None
    competitors: list[str] = []


class SummaryOut(BaseModel):
    text: str
    sources: list[str] = Field(min_length=1)


class CardOut(ImpactCard):
    title: str
    url: str
    source: str
    published_date: date


class AskResponse(BaseModel):
    query_id: int
    status: Status
    message: str | None = None
    summary: list[SummaryOut] = []
    cards: list[CardOut] = []
