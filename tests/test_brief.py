from datetime import date

import pytest

from app import brief as b
from app.config import Settings
from app.schemas import Article, CardOut, SummaryOut

TODAY = date(2026, 11, 3)


def card(i, sentiment="negative", level="high", title=None):
    return CardOut(
        article_id=i, relevant=True, summary=f"Summary {i}.", sentiment=sentiment, level=level,
        reason=f"Reason {i}.", horizon="short", evidence=f"Quote {i}", title=title or f"Story {i}",
        url=f"https://news.com/{i}", source="news.com", published_date="2026-11-02",
    )


def article(i):
    return Article(id=i, title=f"Story {i}", url=f"https://news.com/{i}", source="news.com",
                   published_date="2026-11-02", content="c", is_today_or_yesterday=True)


def fake_runner(question, topic):
    if topic == "market":
        return {"status": "no_news", "message": "No relevant news found.", "summary": [], "cards": [], "articles": []}
    i = 1 if topic == "energy prices" else 2
    cards = [card(i, "negative" if i == 1 else "positive", "medium" if i == 1 else "high",
                  title="Coal <spike> & more" if i == 1 else None), card(3, "neutral", "low")]
    return {"status": "ok", "message": None,
            "summary": [SummaryOut(text=f"Point {i}.", sources=[f"https://news.com/{i}"])],
            "cards": cards, "articles": [article(i), article(3)]}


def settings(**kw):
    base = dict(aws_region="", tavily_api_key="", model_query="", model_impact="", model_summary="",
                max_articles=8, days=30, db_path="", smtp_user="me@gmail.com", smtp_password="app-pass",
                brief_to=("boss@x.com",), app_url="http://localhost:8501")
    return Settings(**{**base, **kw})


@pytest.fixture
def brief(tmp_path):
    return b.build_brief(fake_runner, path=str(tmp_path / "b.db"), today=TODAY)


def test_build_runs_every_question_saves_and_ranks(brief):
    assert [s["topic"] for s in brief["sections"]] == ["energy prices", "policy", "market"]
    assert all(s["query_id"] for s in brief["sections"])                     # saved to the DB
    assert brief["total_cards"] == 3                                          # article 3 deduped
    assert [c["level"] for c in brief["top"]] == ["high", "medium", "low"]   # high impact first
    assert brief["high"] == 1
    assert brief["week"]["total"] == 3                                        # trends read the saved runs


def test_html_is_escaped_and_has_every_part(brief):
    html = b.render_html(brief, "http://localhost:8501")
    assert "Coal &lt;spike&gt; &amp; more" in html and "<spike>" not in html
    assert "Top stories" in html and "This week" in html and "Point 2." in html
    assert "No relevant news found." in html                                  # the no_news section
    assert "https://news.com/2" in html and "http://localhost:8501" in html


def test_subject_and_text(brief):
    assert b.subject(brief).startswith("☀️ Solar news brief · 03 Nov · mood ")
    text = b.render_text(brief, "http://app")
    assert "TOP STORIES" in text and "https://news.com/1" in text and "Open the app: http://app" in text


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def starttls(self):
        self.tls = True

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_send_email_builds_html_and_text(brief):
    FakeSMTP.sent = []
    to = b.send_email(brief, settings(), smtp_cls=FakeSMTP)
    assert to == ["boss@x.com"]
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "boss@x.com" and msg["Subject"].startswith("☀️ Solar news brief")
    assert {p.get_content_type() for p in msg.iter_parts()} == {"text/plain", "text/html"}


def test_missing_smtp_settings_is_a_clear_error(brief):
    with pytest.raises(b.BriefError, match="SMTP_PASSWORD"):
        b.send_email(brief, settings(smtp_password=""), smtp_cls=FakeSMTP)


def test_main_dry_run_writes_html_and_does_not_send(tmp_path, monkeypatch, capsys):
    build = b.build_brief
    monkeypatch.setattr(b, "BRIEF_DIR", tmp_path / "briefs")
    monkeypatch.setattr(b, "build_brief", lambda runner: build(fake_runner, path=str(tmp_path / "m.db"), today=TODAY))
    monkeypatch.setattr(b, "send_email", lambda *a, **k: pytest.fail("must not send"))
    assert b.main(["--dry-run"]) == 0
    written = tmp_path / "briefs" / "brief-2026-11-03.html"
    assert str(written) in capsys.readouterr().out
    assert "Top stories" in written.read_text(encoding="utf-8")


def test_main_stops_early_without_smtp_settings(monkeypatch, capsys):
    monkeypatch.setattr(b, "get_settings", lambda: settings(smtp_user=""))
    monkeypatch.setattr(b, "build_brief", lambda *a: pytest.fail("agents must not run"))
    assert b.main([]) == 2
    assert "SMTP_USER" in capsys.readouterr().err
