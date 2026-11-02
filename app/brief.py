"""Daily morning brief: run a few standing questions, then email a styled impact report.

Run it by hand:      python -m app.brief --dry-run     (writes briefs/brief-<date>.html, sends nothing)
Send it:             python -m app.brief
Schedule it daily:   powershell -File scripts/schedule_brief.ps1 -Time 08:00

The runs are saved like any other question, so they also feed History and Trends.
"""

import argparse
import html
import smtplib
import sys
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from app import trace
from app.config import IST, Settings, get_settings
from app.db import list_impacts, save_run
from app.graph import run_graph
from app.trends import build_trends

# (topic, question) asked every morning.
BRIEF_QUESTIONS = [
    ("energy prices", "What changed in coal, crude oil and power prices that affects solar module makers in India?"),
    ("policy", "Is there new ALMM, BCD, PLI or PM Surya Ghar policy news for Indian solar module manufacturers?"),
    ("market", "How are Indian solar sector stocks and solar module demand moving?"),
]
TOP_STORIES = 6
LEVEL_RANK = {"high": 0, "medium": 1, "low": 2}
SENT = {
    "positive": ("#16a34a", "#dcfce7", "📈"),
    "negative": ("#dc2626", "#fee2e2", "📉"),
    "neutral": ("#64748b", "#f1f5f9", "➖"),
}
BRIEF_DIR = Path(__file__).resolve().parent.parent / "briefs"


class BriefError(Exception):
    """Raised for a setup problem the user must fix (for example missing SMTP settings)."""


# ---------- build ----------

def build_brief(runner: Callable = run_graph, path: str | None = None, today: date | None = None) -> dict:
    """Ask every standing question, save each run, and collect what goes into the email."""
    today = today or datetime.now(IST).date()
    sections, cards = [], {}
    for topic, question in BRIEF_QUESTIONS:
        result = runner(question, topic)
        query_id = save_run(question, topic, result, path=path)
        sections.append({
            "topic": topic, "question": question, "query_id": query_id,
            "status": result["status"], "message": result["message"],
            "summary": [{"text": p.text, "sources": p.sources} for p in result["summary"]],
        })
        for c in result["cards"]:
            cards.setdefault(c.url.rstrip("/").lower(), c.model_dump(mode="json"))

    top = sorted(cards.values(), key=lambda c: (LEVEL_RANK[c["level"]], c["published_date"] < today.isoformat(), c["title"]))
    week = build_trends(list_impacts((today - timedelta(days=6)).isoformat(), path=path), 7, today)
    return {
        "date": today.isoformat(),
        "sections": sections,
        "top": top[:TOP_STORIES],
        "total_cards": len(cards),
        "high": sum(c["level"] == "high" for c in cards.values()),
        "today_counts": {s: sum(c["sentiment"] == s for c in cards.values()) for s in SENT},
        "week": week,
    }


def _mood_word(score: int | None) -> tuple[str, str]:
    if score is None:
        return "😶", "no data"
    if score >= 25:
        return "😄", "positive"
    if score <= -25:
        return "😟", "negative"
    return "😐", "mixed"


def subject(brief: dict) -> str:
    day = datetime.fromisoformat(brief["date"]).strftime("%d %b")
    emoji, _ = _mood_word(brief["week"]["overall"]["score"])
    score = brief["week"]["overall"]["score"]
    mood = f"mood {score:+d} {emoji}" if score is not None else "no news this week"
    return f"☀️ Solar news brief · {day} · {mood} · {brief['high']} high-impact"


# ---------- render ----------

def _e(text) -> str:
    return html.escape(str(text))


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.") or "source"


def _mood_meter(score: int | None) -> str:
    """A -100..+100 bar as an email-safe table."""
    pos = 50 if score is None else (score + 100) / 2
    left, right = max(pos, 1), max(100 - pos, 1)
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:10px 0 4px">'
        f'<tr><td width="{left:.0f}%" style="height:10px;background:linear-gradient(90deg,#dc2626,#f59e0b);'
        'border-radius:999px 0 0 999px;background-color:#f59e0b"></td>'
        '<td width="4" style="background:#0f172a"></td>'
        f'<td width="{right:.0f}%" style="height:10px;background:#e2e8f0;border-radius:0 999px 999px 0"></td></tr></table>'
        '<table role="presentation" width="100%" style="font-size:11px;color:#94a3b8"><tr>'
        '<td>−100 negative</td><td align="right">positive +100</td></tr></table>'
    )


def _story(c: dict) -> str:
    color, bg, icon = SENT[c["sentiment"]]
    quote = (
        f'<div style="margin:8px 0;padding:6px 10px;border-left:3px solid #f59e0b;background:#fffbeb;'
        f'color:#78350f;font-size:13px;font-style:italic">“{_e(c["evidence"])}”</div>' if c.get("evidence") else ""
    )
    return (
        f'<tr><td style="padding:0 0 12px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;'
        f'border-left:5px solid {color};border-radius:12px;background:#ffffff"><tr><td style="padding:14px 16px">'
        f'<a href="{_e(c["url"])}" style="color:#0f172a;font-weight:700;font-size:15px;text-decoration:none">{_e(c["title"])}</a>'
        f'<div style="font-size:12px;color:#64748b;margin:4px 0 8px">{_e(c["source"])} · {_e(c["published_date"])}</div>'
        f'<span style="display:inline-block;padding:2px 9px;border-radius:999px;background:{bg};color:{color};'
        f'font-size:12px;font-weight:700">{icon} {_e(c["sentiment"])}</span> '
        f'<span style="display:inline-block;padding:2px 9px;border-radius:999px;background:#ffedd5;color:#c2410c;'
        f'font-size:12px;font-weight:700">{_e(c["level"])} impact</span> '
        f'<span style="display:inline-block;padding:2px 9px;border-radius:999px;background:#e0f2fe;color:#0369a1;'
        f'font-size:12px;font-weight:700">{_e(c["horizon"])} term</span>'
        f'<div style="font-size:14px;color:#334155;margin-top:8px">{_e(c["summary"])}</div>{quote}'
        f'<div style="font-size:14px;color:#0f172a">💡 <b>Why it matters:</b> {_e(c["reason"])}</div>'
        f'{_also(c)}</td></tr></table></td></tr>'
    )


def _also(c: dict) -> str:
    also = c.get("also_reported_by") or []
    if not also:
        return ""
    links = " · ".join(f'<a href="{_e(s["url"])}" style="color:#ea580c">{_e(s["source"])}</a>' for s in also)
    return f'<div style="font-size:12px;color:#64748b;margin-top:8px">🗞️ Also reported by: {links}</div>'


def _section(s: dict) -> str:
    if s["status"] != "ok" or not s["summary"]:
        note = s["message"] or "No relevant news found."
        body = f'<div style="color:#64748b;font-size:14px">📭 {_e(note)}</div>'
    else:
        items = "".join(
            f'<li style="margin:0 0 6px">{_e(p["text"])} '
            + " ".join(f'<a href="{_e(u)}" style="color:#ea580c;font-size:12px">{_e(_domain(u))}</a>' for u in p["sources"])
            + "</li>"
            for p in s["summary"]
        )
        body = f'<ul style="margin:0;padding-left:18px;font-size:14px;color:#334155">{items}</ul>'
    return (
        f'<tr><td style="padding:0 0 16px"><div style="font-size:12px;font-weight:800;letter-spacing:.08em;'
        f'text-transform:uppercase;color:#ea580c;margin-bottom:6px">{_e(s["topic"])}</div>{body}</td></tr>'
    )


def render_html(brief: dict, app_url: str = "") -> str:
    week = brief["week"]
    o = week["overall"]
    emoji, word = _mood_word(o["score"])
    day = datetime.fromisoformat(brief["date"]).strftime("%A, %d %B %Y")
    counts = brief["today_counts"]
    headline = brief["top"][0]["title"] if brief["top"] else "A quiet news day for your business."

    movers = "".join(
        f'<tr><td style="padding:4px 0;font-size:14px;color:#334155">'
        f'{"📉" if "negative" in h else "📈" if "positive" in h else "✨"} {_e(h)}</td></tr>'
        for h in week["highlights"]
    ) or '<tr><td style="font-size:14px;color:#64748b">No big swings this week.</td></tr>'

    stories = "".join(_story(c) for c in brief["top"]) or (
        '<tr><td style="font-size:14px;color:#64748b">No stories with a business impact today.</td></tr>'
    )
    link = (
        f'<a href="{_e(app_url)}" style="display:inline-block;background:#ea580c;color:#fff;text-decoration:none;'
        f'font-weight:700;padding:10px 18px;border-radius:10px">Open the app and ask a follow-up →</a>'
        if app_url else ""
    )
    stat = (
        '<td align="center" style="padding:10px;background:#fff7ed;border-radius:12px">'
        '<div style="font-size:22px;font-weight:800;color:{c}">{n}</div>'
        '<div style="font-size:11px;color:#9a3412;text-transform:uppercase;letter-spacing:.06em">{l}</div></td>'
    )
    stats = '<td width="8"></td>'.join([
        stat.format(c="#0f172a", n=brief["total_cards"], l="stories"),
        stat.format(c="#dc2626", n=brief["high"], l="high impact"),
        stat.format(c="#16a34a", n=counts["positive"], l="positive"),
        stat.format(c="#dc2626", n=counts["negative"], l="negative"),
    ])
    score = "–" if o["score"] is None else f'{o["score"]:+d}'

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#f1f5f9;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:24px 12px">
<tr><td align="center">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%">

<tr><td style="background:linear-gradient(135deg,#ea580c,#f59e0b 60%,#facc15);background-color:#ea580c;
  border-radius:20px 20px 0 0;padding:26px 28px;color:#ffffff">
  <div style="font-size:12px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;opacity:.9">☀️ Morning brief · {_e(day)}</div>
  <div style="font-size:24px;font-weight:800;line-height:1.25;margin-top:8px">{_e(headline)}</div>
  <div style="font-size:14px;opacity:.95;margin-top:6px">Your solar business news, read by AI agents overnight. Every point links its source.</div>
</td></tr>

<tr><td style="background:#ffffff;padding:22px 28px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{stats}</tr></table>
</td></tr>

<tr><td style="background:#ffffff;padding:0 28px 22px">
  <div style="font-size:16px;font-weight:800;color:#0f172a">{emoji} This week's mood: {score} ({_e(word)})</div>
  {_mood_meter(o["score"])}
  <table role="presentation" width="100%" style="margin-top:8px">{movers}</table>
</td></tr>

<tr><td style="background:#ffffff;padding:0 28px 8px">
  <div style="font-size:16px;font-weight:800;color:#0f172a;margin-bottom:12px">🗞️ Top stories</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{stories}</table>
</td></tr>

<tr><td style="background:#ffffff;padding:6px 28px 10px">
  <div style="font-size:16px;font-weight:800;color:#0f172a;margin-bottom:12px">✨ In short, by topic</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(_section(s) for s in brief["sections"])}</table>
</td></tr>

<tr><td style="background:#ffffff;border-radius:0 0 20px 20px;padding:8px 28px 26px" align="center">
  {link}
  <div style="font-size:12px;color:#94a3b8;margin-top:14px">News from the last 30 days only. Impacts are AI analysis of the
  article text, not advice. Sent by your Agentic News Impact System.</div>
</td></tr>

</table></td></tr></table></body></html>"""


def render_text(brief: dict, app_url: str = "") -> str:
    """Plain-text version for mail apps that do not show HTML."""
    o = brief["week"]["overall"]
    lines = [f"Solar news brief - {brief['date']}", ""]
    if o["score"] is not None:
        lines.append(f"This week's mood: {o['score']:+d} ({_mood_word(o['score'])[1]})")
    lines += [f"- {h}" for h in brief["week"]["highlights"]] + ["", "TOP STORIES"]
    for c in brief["top"]:
        lines += [f"* {c['title']} [{c['sentiment']}, {c['level']} impact]", f"  {c['reason']}", f"  {c['url']}"]
    for s in brief["sections"]:
        lines += ["", s["topic"].upper()]
        lines += [f"- {p['text']} ({', '.join(p['sources'])})" for p in s["summary"]] or [f"- {s['message'] or 'No relevant news found.'}"]
    if app_url:
        lines += ["", f"Open the app: {app_url}"]
    return "\n".join(lines)


# ---------- send ----------

def check_email_settings(settings: Settings, recipients: list[str]) -> None:
    missing = [name for name, value in [
        ("SMTP_USER", settings.smtp_user), ("SMTP_PASSWORD", settings.smtp_password), ("BRIEF_TO", recipients),
    ] if not value]
    if missing:
        raise BriefError(f"Set {', '.join(missing)} in .env to send the brief (or use --dry-run).")


def send_email(brief: dict, settings: Settings, to: list[str] | None = None, smtp_cls=smtplib.SMTP) -> list[str]:
    """Send the brief over SMTP with STARTTLS. Returns the recipients."""
    recipients = list(to or settings.brief_to)
    check_email_settings(settings, recipients)
    msg = EmailMessage()
    msg["Subject"] = subject(brief)
    msg["From"] = settings.smtp_user
    msg["To"] = ", ".join(recipients)
    msg.set_content(render_text(brief, settings.app_url))
    msg.add_alternative(render_html(brief, settings.app_url), subtype="html")
    with smtp_cls(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)
    return recipients


def save_html(brief: dict, app_url: str = "", folder: Path | None = None) -> Path:
    folder = folder or BRIEF_DIR  # read at call time so tests can point it elsewhere
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"brief-{brief['date']}.html"
    out.write_text(render_html(brief, app_url), encoding="utf-8")
    return out


def main(argv: list[str] | None = None, runner: Callable = run_graph) -> int:
    parser = argparse.ArgumentParser(description="Build and email the daily solar news brief.")
    parser.add_argument("--dry-run", action="store_true", help="only write the HTML file, do not send")
    parser.add_argument("--to", help="comma-separated recipients (default: BRIEF_TO in .env)")
    args = parser.parse_args(argv)

    settings = get_settings()
    to = [a.strip() for a in args.to.split(",") if a.strip()] if args.to else None
    if not args.dry_run:
        # Fail before the slow agent runs if the email cannot be sent anyway.
        try:
            check_email_settings(settings, to or list(settings.brief_to))
        except BriefError as exc:
            print(f"✖ {exc}", file=sys.stderr)
            return 2

    brief = build_brief(runner)
    path = save_html(brief, settings.app_url)
    trace.emit("run", "done", f"brief saved to {path}")
    if args.dry_run:
        print(path)
        return 0
    try:
        sent_to = send_email(brief, settings, to)
    except BriefError as exc:
        print(f"✖ {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # network, login, ...
        print(f"✖ Could not send the email: {exc}", file=sys.stderr)
        return 1
    print(f"✔ Brief sent to {', '.join(sent_to)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
