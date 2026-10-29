from app.nodes.impact_analyzer import MAX_CONTENT_CHARS, ImpactOutput, analyze_impacts
from app.schemas import Article


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


def test_builds_cards_with_code_set_ids():
    llm = FakeLLM([[output(), output(relevant=False)]])
    cards = analyze_impacts("q", [article(7), article(9)], llm=llm)
    assert [c.article_id for c in cards] == [7, 9]
    assert [c.relevant for c in cards] == [True, False]


def test_prompt_has_article_text_and_question_only():
    llm = FakeLLM([[output()]])
    analyze_impacts("my question", [article(1, content="Specific body text.")], llm=llm)
    user_msg = llm.inputs[0][0][1][1]
    assert "my question" in user_msg and "Specific body text." in user_msg
    assert "https://s.com/1" not in user_msg  # LLM never sees URLs


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


def test_relevant_output_must_have_level():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ImpactOutput(relevant=True, summary="s", sentiment="negative", reason="r", horizon="short")


def test_no_articles_makes_no_call():
    assert analyze_impacts("q", [], llm=FakeLLM([])) == []
