from datetime import date, datetime

import pytest

from app.config import IST
from app.db import get_run, save_run
from app.nodes.filter_rank import filter_rank
from app.nodes.story_merge import same_story
from app.nodes.validator import validate
from app.schemas import ImpactCard, RawArticle, SummaryPoint

D = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=IST)


@pytest.mark.parametrize("a,b", [
    ("Coal prices hit six-month high as imports slow", "Coal prices hit 6-month high as imports slow - The Economic Times"),
    ("Government extends ALMM list for solar modules to cells", "Govt extends ALMM list for solar modules to cells | Mint"),
    ("Waaree Energies shares surge 8% after strong Q2 results", "Waaree Energies shares surge after strong Q2 results"),
])
def test_same_story_on_different_sites(a, b):
    assert same_story(a, D, b, D)


@pytest.mark.parametrize("a,b", [
    ("Coal prices hit six-month high as imports slow", "Crude oil prices fall as OPEC raises output"),
    ("Solar module prices fall in India", "Solar module exports rise to the US"),
    ("Nifty Energy index rallies on renewables push", "Nifty Bank index falls on profit booking"),
    # seen in real data: two different brokers, two different stories
    ("Susquehanna cuts First Solar stock price target on lower guidance",
     "Freedom Broker cuts First Solar stock price target on guidance reduction"),
])
def test_different_stories_stay_apart(a, b):
    assert not same_story(a, D, b, D)


def test_same_title_days_apart_is_a_new_story():
    t = "Coal prices hit six-month high as imports slow"
    assert not same_story(t, D, t, date(2026, 10, 25))


def raw(title, url, d="2026-11-02", score=0.5):
    return RawArticle(title=title, url=url, content=f"{title}. Body text.", published_date=d, score=score)


def test_filter_rank_merges_before_the_top_n_cut():
    items = [
        raw("Coal prices hit six-month high as imports slow", "https://www.et.com/coal", score=0.9),
        raw("Coal prices hit 6-month high as imports slow - Mint", "https://mint.com/coal", score=0.8),
        raw("Coal prices hit six month high as imports slow | BS", "https://bs.com/coal", score=0.7),
        raw("ALMM list extended to solar cells", "https://pv.com/almm"),
    ]
    out = filter_rank(items, max_articles=2, now=NOW)
    assert [a.title for a in out] == ["Coal prices hit six-month high as imports slow", "ALMM list extended to solar cells"]
    assert [s.source for s in out[0].also] == ["mint.com", "bs.com"]   # the best ranked report leads
    assert out[1].also == [] and [a.id for a in out] == [1, 2]


def test_also_reported_by_reaches_the_card_and_survives_the_db(tmp_path):
    arts = filter_rank([
        raw("Coal prices hit six-month high as imports slow", "https://et.com/coal"),
        raw("Coal prices hit 6-month high as imports slow - Mint", "https://mint.com/coal"),
    ], now=NOW)
    card = ImpactCard(article_id=1, relevant=True, summary="Coal prices hit six-month high as imports slow.",
                      sentiment="negative", level="medium", reason="Costs may rise.", horizon="short",
                      evidence="Coal prices hit six-month high")
    cards, _ = validate([card], [SummaryPoint(text="Coal prices hit a high.", source_ids=[1])], arts, "coal")
    assert [s.url for s in cards[0].also_reported_by] == ["https://mint.com/coal"]

    result = {"status": "ok", "message": None, "summary": [], "cards": cards, "articles": arts}
    qid = save_run("coal?", None, result, path=str(tmp_path / "m.db"))
    assert get_run(qid, path=str(tmp_path / "m.db")).cards[0].also_reported_by[0].source == "mint.com"
