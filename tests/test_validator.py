from app.nodes.validator import validate
from app.schemas import Article, ImpactCard, SummaryPoint

TEXT = "Solar import duty is 40 percent from April."


def article(i, content=TEXT):
    return Article(
        id=i, title=f"title {i}", url=f"https://s.com/{i}", source="s.com",
        published_date="2026-10-29", content=content, is_today_or_yesterday=True,
    )


def card(i=1, summary="Solar import duty is 40 percent", reason="Costs may go up",
         relevant=True, evidence="Solar import duty is 40 percent from April"):
    return ImpactCard(
        article_id=i, relevant=relevant, summary=summary, sentiment="negative",
        level="high", reason=reason, horizon="short", evidence=evidence,
    )


# --- cards -------------------------------------------------------------------

def test_valid_card_gets_article_fields():
    cards, _ = validate([card()], [], [article(1)])
    assert len(cards) == 1
    assert cards[0].url == "https://s.com/1" and cards[0].title == "title 1"
    assert cards[0].evidence == "Solar import duty is 40 percent from April"


def test_drops_card_with_unknown_article_id():
    cards, _ = validate([card(i=99)], [], [article(1)])
    assert cards == []


def test_drops_irrelevant_card():
    cards, _ = validate([card(relevant=False)], [], [article(1)])
    assert cards == []


def test_drops_card_without_evidence(caplog):
    caplog.set_level("WARNING", logger="app.nodes.validator")
    cards, _ = validate([card(evidence="")], [], [article(1)])
    assert cards == [] and "evidence not found" in caplog.text


def test_drops_card_with_made_up_evidence():
    fake = "Crude oil and coal price rises will raise solar module production costs"
    cards, _ = validate([card(evidence=fake)], [], [article(1)])
    assert cards == []


def test_keeps_card_whose_quote_differs_by_one_word():
    art = article(1, content="The ministry said the solar import duty will be 40 percent from April onwards.")
    near = "the solar import duty will be 40 percent from April onward"
    cards, _ = validate([card(evidence=near)], [], [art])
    assert len(cards) == 1


def test_drops_card_whose_summary_is_not_in_the_article(caplog):
    caplog.set_level("WARNING", logger="app.nodes.validator")
    c = card(summary="Transportation costs and labour shortages squeeze factory margins")
    cards, _ = validate([c], [], [article(1)])
    assert cards == [] and "summary grounding" in caplog.text


def test_drops_card_whose_summary_repeats_question_terms_missing_from_article():
    art = article(1, content="Volatility in material costs affects solar panel manufacturing economics and prices.")
    c = card(summary="Crude oil volatility in material costs affects solar panel manufacturing",
             evidence="Volatility in material costs affects solar panel manufacturing economics")
    cards, _ = validate([c], [], [art], question_text="crude oil prices and module cost")
    assert cards == []


def test_drops_card_with_invented_number():
    cards, _ = validate([card(summary="Solar import duty is 25 percent")], [], [article(1)])
    assert cards == []


def test_drops_card_with_invented_number_in_the_reason():
    cards, _ = validate([card(reason="Costs may rise 15 percent")], [], [article(1)])
    assert cards == []


def test_number_comma_normalized():
    art = article(1, content="Capacity of 1,200 MW added.")
    c = card(summary="Capacity of 1200 MW added", evidence="Capacity of 1,200 MW added")
    cards, _ = validate([c], [], [art])
    assert len(cards) == 1


# --- summary points ----------------------------------------------------------

def test_point_gets_urls_from_ids():
    pts = [SummaryPoint(text="Duty is 40 percent", source_ids=[1, 2])]
    _, out = validate([card(1), card(2)], pts, [article(1), article(2)])
    assert out[0].sources == ["https://s.com/1", "https://s.com/2"]


def test_point_drops_invalid_ids_but_keeps_valid():
    pts = [SummaryPoint(text="Solar import duty is 40 percent", source_ids=[1, 99])]
    _, out = validate([card(1)], pts, [article(1)])
    assert out[0].sources == ["https://s.com/1"]


def test_point_dropped_when_all_ids_invalid():
    pts = [SummaryPoint(text="Solar import duty is 40 percent", source_ids=[99])]
    _, out = validate([card(1)], pts, [article(1)])
    assert out == []


def test_point_dropped_when_source_card_removed():
    pts = [SummaryPoint(text="Solar import duty is 40 percent", source_ids=[1])]
    _, out = validate([card(1, relevant=False)], pts, [article(1)])
    assert out == []


def test_point_dropped_when_claim_is_not_in_the_sources():
    text = "Transportation costs and labour shortages will squeeze factory profitability"
    _, out = validate([card(1)], [SummaryPoint(text=text, source_ids=[1])], [article(1)])
    assert out == []


def test_paraphrased_point_with_plurals_is_kept():
    content = "Solar module makers face higher import duties on cells."
    c = card(1, summary=content, evidence=content)
    pts = [SummaryPoint(text="Module makers face higher import duty on solar cells", source_ids=[1])]
    _, out = validate([c], pts, [article(1, content=content)])
    assert len(out) == 1


def test_point_repeating_question_terms_missing_from_sources_is_dropped(caplog):
    content = "Volatility in material costs affects solar panel manufacturing economics and prices."
    c = card(1, summary="Material costs volatility affects solar panel manufacturing", evidence=content)
    # Passes the grounding check (only "crude" is new) but repeats the question's own word.
    pts = [SummaryPoint(text="Crude oil prices affect material costs for solar panel manufacturing", source_ids=[1])]
    caplog.set_level("WARNING", logger="app.nodes.validator")
    _, out = validate([c], pts, [article(1, content=content)], question_text="how do crude oil prices affect module cost")
    assert out == []
    assert "question terms" in caplog.text and "crud" in caplog.text


def test_point_using_question_terms_that_the_sources_contain_is_kept():
    content = "Crude oil and coal prices rose, raising material costs for solar panel makers."
    c = card(1, summary="Crude oil and coal prices rose, raising material costs", evidence=content)
    pts = [SummaryPoint(text="Crude oil and coal prices rose, raising material costs", source_ids=[1])]
    _, out = validate([c], pts, [article(1, content=content)],
                      question_text="how do crude oil and coal prices affect module cost")
    assert len(out) == 1


def test_question_text_is_optional():
    pts = [SummaryPoint(text="Duty is 40 percent", source_ids=[1])]
    _, out = validate([card(1)], pts, [article(1)])
    assert len(out) == 1


def test_point_cannot_borrow_words_from_the_card_reason():
    # The reason is the model's inference, not something the news said.
    c = card(1, reason="Rooftop installers may see higher demand and lower margins")
    pts = [SummaryPoint(text="Rooftop installers may see higher demand and lower margins", source_ids=[1])]
    _, out = validate([c], pts, [article(1)])
    assert out == []


def test_point_dropped_for_invented_number():
    pts = [SummaryPoint(text="Solar import duty is 12 percent", source_ids=[1])]
    _, out = validate([card(1)], pts, [article(1)])
    assert out == []


# --- logging -------------------------------------------------------------------

def test_drops_are_logged_with_a_reason(caplog):
    caplog.set_level("WARNING", logger="app.nodes.validator")
    pts = [
        SummaryPoint(text="Transportation costs and labour shortages hurt factory profitability", source_ids=[1]),
        SummaryPoint(text="Duty is 40 percent", source_ids=[99]),
        SummaryPoint(text="Duty is 99 percent", source_ids=[1]),
    ]
    validate([card(1)], pts, [article(1)])
    messages = " | ".join(r.getMessage() for r in caplog.records)
    assert "grounding" in messages and "no valid source" in messages and "number not found" in messages


def test_irrelevant_cards_are_not_logged_as_drops(caplog):
    caplog.set_level("WARNING", logger="app.nodes.validator")
    validate([card(1, relevant=False)], [], [article(1)])
    assert caplog.records == []
