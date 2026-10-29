import pytest
from pydantic import ValidationError

from app.schemas import Article, AskRequest, AskResponse, ImpactCard, RawArticle, SummaryPoint

CARD = {
    "article_id": 1,
    "relevant": True,
    "summary": "[news summary]",
    "sentiment": "negative",
    "level": "medium",
    "reason": "[ek line reason]",
    "horizon": "short",
}


def test_raw_article_date_optional():
    a = RawArticle(title="t", url="https://x.com/a", content="c")
    assert a.published_date is None


def test_article_parses_iso_date():
    a = Article(
        id=1, title="t", url="https://x.com/a", source="x.com",
        published_date="2026-10-28", content="c", is_today_or_yesterday=True,
    )
    assert a.published_date.isoformat() == "2026-10-28"


def test_article_rejects_bad_date():
    with pytest.raises(ValidationError):
        Article(
            id=1, title="t", url="u", source="s",
            published_date="yesterday", content="c", is_today_or_yesterday=True,
        )


def test_impact_card_valid():
    assert ImpactCard(**CARD).level == "medium"


@pytest.mark.parametrize("field,bad", [
    ("sentiment", "good"),
    ("level", "very high"),
    ("horizon", "medium"),
])
def test_impact_card_rejects_bad_enum(field, bad):
    with pytest.raises(ValidationError):
        ImpactCard(**{**CARD, field: bad})


def test_summary_point_needs_source():
    with pytest.raises(ValidationError):
        SummaryPoint(text="point", source_ids=[])


def test_ask_request_rejects_empty_question():
    with pytest.raises(ValidationError):
        AskRequest(question="")


def test_ask_response_no_news():
    r = AskResponse(query_id=1, status="no_news", message="No relevant news found")
    assert r.cards == [] and r.summary == []
