import pytest

from app.nodes.impact_analyzer import MAX_CONTENT_CHARS, ImpactOutput, analyze_impacts
from app.schemas import Article


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr("app.nodes.impact_analyzer.RETRY_DELAY_SECONDS", 0)


def article(i, content="Coal prices rose."):
    return Article(
        id=i, title=f"title {i}", url=f"https://s.com/{i}", source="s.com",
        published_date="2026-10-29", content=content, is_today_or_yesterday=True,
    )


def output(relevant=True, **kw):
    base = dict(
        relevant=relevant, summary="s", sentiment="negative",
        level="medium", reason="r", horizon="short",
    )
    return ImpactOutput(**{**base, **kw})


class FakeLLM:
    """batch() returns scripted outputs (or exceptions), one list per call."""

    def __init__(self, batches):
        self.batches, self.inputs = list(batches), []

    def with_structured_output(self, schema):
        return self

    def batch(self, inputs, config=None, return_exceptions=False):
        self.inputs.append(inputs)
        return self.batches.pop(0)

    def batch_as_completed(self, inputs, config=None, return_exceptions=False):
        # finish in reverse order to prove results are matched back by position
        outputs = self.batch(inputs, config, return_exceptions)
        return reversed(list(enumerate(outputs)))


def test_builds_cards_with_code_set_ids():
    llm = FakeLLM([[output(), output(relevant=False)]])
    cards = analyze_impacts("q", [article(7), article(9)], llm=llm)
    assert [c.article_id for c in cards] == [7, 9]
    assert [c.relevant for c in cards] == [True, False]


def test_prompt_has_article_text_only():
    llm = FakeLLM([[output()]])
    analyze_impacts("my question", [article(1, content="Specific body text.")], llm=llm)
    user_msg = llm.inputs[0][0][1][1]
    assert "Specific body text." in user_msg
    assert "my question" not in user_msg  # the question made the model tie every article to it
    assert "https://s.com/1" not in user_msg  # LLM never sees URLs


def test_evidence_is_passed_to_the_card():
    llm = FakeLLM([[output(evidence="Coal prices rose")]])
    cards = analyze_impacts("q", [article(1)], llm=llm)
    assert cards[0].evidence == "Coal prices rose"


def test_irrelevant_output_may_skip_evidence():
    out = ImpactOutput(relevant=False, summary="s", reason="r")
    assert out.evidence == ""


def test_truncates_long_content():
    llm = FakeLLM([[output()]])
    analyze_impacts("q", [article(1, content="x" * (MAX_CONTENT_CHARS + 500))], llm=llm)
    body = llm.inputs[0][0][1][1].split("Text: ", 1)[1]
    assert len(body) == MAX_CONTENT_CHARS


def test_retries_only_failed_articles_then_succeeds():
    llm = FakeLLM([[output(), RuntimeError("bad json")], [output(level="high")]])
    cards = analyze_impacts("q", [article(1), article(2)], llm=llm)
    assert [c.article_id for c in cards] == [1, 2]
    assert len(llm.inputs[1]) == 1  # second call only for the failed article
    assert cards[1].level == "high"


def test_drops_article_that_keeps_failing():
    llm = FakeLLM([[output(), RuntimeError("x")], [RuntimeError("x")], [RuntimeError("x")]])
    cards = analyze_impacts("q", [article(1), article(2)], llm=llm)
    assert [c.article_id for c in cards] == [1]
    assert len(llm.inputs) == 3  # first try + 2 retries


def test_irrelevant_output_may_skip_fields():
    out = ImpactOutput(relevant=False, summary="s", reason="r")
    assert (out.sentiment, out.level, out.horizon) == ("neutral", "low", "long")


def test_relevant_output_without_level_gets_the_cautious_low():
    # A live run lost a relevant card because the model left out "level" three times.
    out = ImpactOutput(relevant=True, summary="s", sentiment="negative", reason="r", horizon="short")
    assert out.level == "low"


def test_relevant_output_still_needs_sentiment_and_horizon():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ImpactOutput(relevant=True, summary="s", reason="r", level="high")


def test_no_articles_makes_no_call():
    assert analyze_impacts("q", [], llm=FakeLLM([])) == []
