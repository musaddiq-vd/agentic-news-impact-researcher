import pytest

from app.nodes.summarizer import MAX_POINTS, SummaryOutput, summarize
from app.schemas import Article, ImpactCard, SummaryPoint


def article(i):
    return Article(
        id=i, title=f"title {i}", url=f"https://s.com/{i}", source="s.com",
        published_date="2026-10-29", content="secret raw body", is_today_or_yesterday=True,
    )


def card(i, relevant=True):
    return ImpactCard(
        article_id=i, relevant=relevant, summary=f"card summary {i}",
        sentiment="negative", level="high", reason=f"reason {i}", horizon="short",
    )


def points(n):
    return SummaryOutput(points=[{"text": f"p{i}", "source_ids": [1]} for i in range(n)])


class FakeLLM:
    """invoke() returns scripted outputs; an Exception in the script is raised."""

    def __init__(self, script):
        self.script, self.messages = list(script), []

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        self.messages.append(messages)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_returns_points():
    llm = FakeLLM([points(3)])
    assert len(summarize("q", [card(1)], [article(1)], llm=llm).points) == 3


@pytest.mark.parametrize("direct_ids,expected", [
    ([1], True),        # a shown item directly answers
    ([], False),        # the model says none does
    ([99], False),      # an ID that was never shown does not count
    ([2], False),       # item 2 exists but its card is irrelevant, so it was not shown
    (None, None),       # the model did not say
])
def test_answers_question_comes_from_the_direct_item_ids(direct_ids, expected):
    out = SummaryOutput(direct_item_ids=direct_ids, points=[{"text": "p", "source_ids": [1]}])
    cards = [card(1), card(2, relevant=False)]
    result = summarize("q", cards, [article(1), article(2)], llm=FakeLLM([out]))
    assert result.answers_question is expected


def test_missing_ids_field_means_unknown_not_a_failure():
    out = SummaryOutput.model_validate({"points": [{"text": "p", "source_ids": [1]}]})
    result = summarize("q", [card(1)], [article(1)], llm=FakeLLM([out]))
    assert len(result.points) == 1 and result.answers_question is None


def test_only_relevant_cards_reach_llm_and_no_urls_or_raw_text():
    llm = FakeLLM([points(1)])
    summarize("q", [card(1), card(2, relevant=False)], [article(1), article(2)], llm=llm)
    user_msg = llm.messages[0][1][1]
    assert "card summary 1" in user_msg
    assert "card summary 2" not in user_msg
    assert "reason 1" not in user_msg and "impact:" not in user_msg  # no impact analysis
    assert "https://" not in user_msg and "secret raw body" not in user_msg


def test_caps_at_max_points():
    llm = FakeLLM([points(8)])
    assert len(summarize("q", [card(1)], [article(1)], llm=llm).points) == MAX_POINTS


def test_retries_then_succeeds():
    llm = FakeLLM([RuntimeError("bad json"), points(2)])
    assert len(summarize("q", [card(1)], [article(1)], llm=llm).points) == 2


def test_returns_empty_when_it_keeps_failing():
    llm = FakeLLM([RuntimeError("x"), RuntimeError("x")])
    assert summarize("q", [card(1)], [article(1)], llm=llm) == ([], None)


def test_point_without_sources_is_dropped_but_others_are_kept():
    out = SummaryOutput(points=[
        {"text": "supported", "source_ids": [1]},
        {"text": "no source", "source_ids": []},
    ])
    result = summarize("q", [card(1)], [article(1)], llm=FakeLLM([out]))
    assert [p.text for p in result.points] == ["supported"]


def test_retries_when_every_point_lacks_sources():
    bad = SummaryOutput(points=[{"text": "no source"}])
    llm = FakeLLM([bad, points(2)])
    assert len(summarize("q", [card(1)], [article(1)], llm=llm).points) == 2


def test_no_points_but_model_says_news_does_not_answer(caplog):
    out = SummaryOutput(direct_item_ids=[], points=[])
    caplog.set_level("WARNING", logger="app.nodes.summarizer")
    result = summarize("q", [card(1)], [article(1)], llm=FakeLLM([out, out]))
    assert result == ([], False)
    assert "no usable points" in caplog.text


def test_no_relevant_cards_makes_no_call():
    result = summarize("q", [card(1, relevant=False)], [article(1)], llm=FakeLLM([]))
    assert result == ([], None)
