from app.nodes.validator import validate
from app.schemas import Article, ImpactCard, SummaryPoint


def article(i, content="Solar import duty is 40 percent from April."):
    return Article(
        id=i, title=f"title {i}", url=f"https://s.com/{i}", source="s.com",
        published_date="2026-10-29", content=content, is_today_or_yesterday=True,
    )


def card(i=1, summary="Duty rises", reason="Costs go up", relevant=True):
    return ImpactCard(
        article_id=i, relevant=relevant, summary=summary,
        sentiment="negative", level="high", reason=reason, horizon="short",
    )


def test_valid_card_gets_article_fields():
    cards, _ = validate([card()], [], [article(1)])
    assert len(cards) == 1
    assert cards[0].url == "https://s.com/1" and cards[0].title == "title 1"


def test_drops_card_with_unknown_article_id():
    cards, _ = validate([card(i=99)], [], [article(1)])
    assert cards == []


def test_drops_irrelevant_card():
    cards, _ = validate([card(relevant=False)], [], [article(1)])
    assert cards == []


def test_drops_card_with_invented_number():
    cards, _ = validate([card(summary="Duty is 25 percent")], [], [article(1)])
    assert cards == []


def test_keeps_card_with_number_from_article():
    cards, _ = validate([card(summary="Duty is 40 percent")], [], [article(1)])
    assert len(cards) == 1


def test_number_comma_normalized():
    art = article(1, content="Capacity of 1,200 MW added.")
    cards, _ = validate([card(summary="Added 1200 MW")], [], [art])
    assert len(cards) == 1


def test_point_gets_urls_from_ids():
    pts = [SummaryPoint(text="Duty is 40 percent", source_ids=[1, 2])]
    _, out = validate([card(1), card(2)], pts, [article(1), article(2)])
    assert out[0].sources == ["https://s.com/1", "https://s.com/2"]


def test_point_drops_invalid_ids_but_keeps_valid():
    pts = [SummaryPoint(text="Duty rises", source_ids=[1, 99])]
    _, out = validate([card(1)], pts, [article(1)])
    assert out[0].sources == ["https://s.com/1"]


def test_point_dropped_when_all_ids_invalid():
    pts = [SummaryPoint(text="Duty rises", source_ids=[99])]
    _, out = validate([card(1)], pts, [article(1)])
    assert out == []


def test_point_dropped_when_source_card_removed():
    pts = [SummaryPoint(text="Duty rises", source_ids=[1])]
    _, out = validate([card(1, relevant=False)], pts, [article(1)])
    assert out == []


def test_point_dropped_when_claim_is_not_in_the_sources():
    # Every number is fine, but the claim itself is not in the article or card.
    text = "Transportation costs and labour shortages will squeeze factory profitability"
    pts = [SummaryPoint(text=text, source_ids=[1])]
    _, out = validate([card(1)], pts, [article(1)])
    assert out == []


def test_paraphrased_point_with_plurals_is_kept():
    art = article(1, content="Solar module makers face higher import duties on cells.")
    pts = [SummaryPoint(text="Module makers face higher import duty on solar cells", source_ids=[1])]
    _, out = validate([card(1)], pts, [art])
    assert len(out) == 1


def test_point_may_use_words_from_the_card_text():
    c = card(1, summary="Net metering rules were relaxed", reason="Rooftop demand may rise")
    pts = [SummaryPoint(text="Relaxed net metering rules may raise rooftop demand", source_ids=[1])]
    _, out = validate([c], pts, [article(1, content="Solar import duty is 40 percent from April.")])
    assert len(out) == 1


def test_point_dropped_for_invented_number():
    pts = [SummaryPoint(text="Prices fell 12 percent", source_ids=[1])]
    _, out = validate([card(1)], pts, [article(1)])
    assert out == []
