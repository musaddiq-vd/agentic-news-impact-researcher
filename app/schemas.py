"""Data models (PLAN.md section 1)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.profile import TOPICS

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


class SourceRef(BaseModel):
    """Another site that reported the same story."""

    title: str
    url: str
    source: str


class Article(BaseModel):
    """Article after filtering and ranking."""

    id: int
    title: str
    url: str
    source: str
    published_date: date
    content: str
    is_today_or_yesterday: bool
    also: list[SourceRef] = []  # same story on other sites; only this article goes to the LLM


class ImpactCard(BaseModel):
    """LLM output: business impact of one article. The LLM never returns URLs."""

    article_id: int
    relevant: bool
    summary: str
    sentiment: Sentiment
    level: Level
    reason: str
    horizon: Horizon
    evidence: str = ""  # exact quote from the article that backs the card; checked by the validator


class SummaryPoint(BaseModel):
    """LLM summary point: article IDs only; code adds the URLs."""

    text: str
    source_ids: list[int] = Field(min_length=1)


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=500)
    topic: str | None = None

    @field_validator("topic")
    @classmethod
    def _known_topic(cls, v):
        if v is not None and v not in TOPICS:
            raise ValueError(f"topic must be one of {TOPICS}")
        return v


class HistoryItem(BaseModel):
    query_id: int
    question: str
    status: str
    created_at: str


class SummaryOut(BaseModel):
    text: str
    sources: list[str] = Field(min_length=1)


class CardOut(ImpactCard):
    title: str
    url: str
    source: str
    published_date: date
    also_reported_by: list[SourceRef] = []


class FollowupRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query_id: int
    question: str = Field(min_length=1, max_length=500)


class FollowupOut(BaseModel):
    question: str
    answer: str
    sources: list[str] = []
    grounded: bool  # False when the answer cites no news item
    created_at: str


class AskResponse(BaseModel):
    query_id: int
    question: str = ""
    status: Status
    message: str | None = None
    summary: list[SummaryOut] = []
    cards: list[CardOut] = []
    followups: list[FollowupOut] = []
