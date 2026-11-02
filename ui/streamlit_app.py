"""Streamlit UI. Talks only to the FastAPI backend; never touches the graph or the DB."""

import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # makes `app` importable

from app.config import IST  # noqa: E402
from app.profile import BUSINESS, DEPENDENCIES, LOCATION, PRODUCTS, TOPICS  # noqa: E402
from ui import board as agent_board  # noqa: E402
from ui.trends_view import trends_page  # noqa: E402

PAGES = {"Ask": "🔍 Ask", "Trends": "📈 Trends", "History": "🕘 History"}

load_dotenv()
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT = 150  # /ask can take up to a minute or two

SENTIMENT_COLOR = {"positive": "green", "negative": "red", "neutral": "gray"}
SENTIMENT_HEX = {"positive": "#16a34a", "negative": "#dc2626", "neutral": "#94a3b8"}
SENTIMENT_ICON = {"positive": "📈", "negative": "📉", "neutral": "➖"}
LEVEL_RANK = {"high": 0, "medium": 1, "low": 2}
LEVEL_HEX = {"high": "#ea580c", "medium": "#f59e0b", "low": "#fcd34d"}
HORIZON_HEX = {"short": "#0ea5e9", "long": "#6366f1"}

EXAMPLE_QUESTIONS = [
    "How will rising coal prices affect my module production cost?",
    "Koi nayi solar policy aayi hai kya jo mere business ko affect kare?",
    "What is happening with polysilicon import prices?",
    "How are solar sector stocks doing this month?",
]

CSS = """
<style>
.block-container { padding-top: 3.5rem; max-width: 1100px; }

.st-key-hero {
  background: linear-gradient(135deg, #ea580c 0%, #f59e0b 60%, #facc15 100%);
  border-radius: 20px; padding: 1.6rem 1.9rem 1.2rem;
  box-shadow: 0 10px 30px rgba(234, 88, 12, .25);
}
.st-key-hero h1 { color: #fff !important; padding: 0 !important; letter-spacing: -.5px; }
.st-key-hero p, .st-key-hero [data-testid="stCaptionContainer"] { color: #fff !important; opacity: 1; font-size: .95rem; }
.hero-eyebrow {
  display: inline-block; font-size: .75rem; font-weight: 700; letter-spacing: .08em;
  text-transform: uppercase; color: #fff; background: rgba(255, 255, 255, .22);
  padding: .2rem .65rem; border-radius: 999px;
}

[data-testid="stMetric"] {
  background: rgba(245, 158, 11, .07); border: 1px solid rgba(245, 158, 11, .25);
  border-radius: 14px; padding: .75rem 1rem;
}

.st-key-summary {
  background: rgba(250, 204, 21, .08); border: 1px solid rgba(245, 158, 11, .3);
  border-radius: 16px; padding: 1rem 1.3rem;
}

div[class*="st-key-chat-"] {
  border: 1px solid rgba(99, 102, 241, .25); background: rgba(99, 102, 241, .04);
  border-radius: 18px; padding: 1rem 1.2rem; margin-top: 1rem;
}

div[class*="st-key-card-"] { border-radius: 14px; transition: transform .15s ease, box-shadow .15s ease; }
div[class*="st-key-card-"]:hover { transform: translateY(-2px); box-shadow: 0 10px 24px rgba(0, 0, 0, .08); }
div[class*="st-key-card-positive"] { border-left: 6px solid #16a34a !important; }
div[class*="st-key-card-negative"] { border-left: 6px solid #dc2626 !important; }
div[class*="st-key-card-neutral"]  { border-left: 6px solid #94a3b8 !important; }
div[class*="st-key-card-"] blockquote {
  border-left: 3px solid #f59e0b; margin: .2rem 0 .4rem; padding: .3rem .8rem;
  background: rgba(245, 158, 11, .07); border-radius: 0 8px 8px 0;
}

.split-label { font-size: .85rem; font-weight: 600; margin: .6rem 0 .25rem; opacity: .85; }
.split-bar { display: flex; height: 16px; border-radius: 999px; overflow: hidden; background: rgba(128,128,128,.15); }
.split-bar span { display: block; height: 100%; }
.split-legend { display: flex; flex-wrap: wrap; gap: .9rem; font-size: .8rem; margin-top: .35rem; opacity: .9; }
.split-legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: .3rem; }

.status-dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: .4rem; }
</style>
"""


def call_api(method: str, path: str, **kwargs) -> tuple[object | None, str | None]:
    """Return (json, None) on success or (None, user-friendly error)."""
    try:
        r = httpx.request(method, API_URL + path, timeout=REQUEST_TIMEOUT, **kwargs)
    except httpx.ConnectError:
        return None, "The API is not running. Start it with: uvicorn app.api:app"
    except httpx.TimeoutException:
        return None, "The request timed out. Please try again."
    if r.status_code in (409, 502):  # the API's own message is meant for the user
        try:
            return None, r.json()["detail"]
        except Exception:
            pass
    if r.status_code >= 400:
        return None, _http_error(r.status_code)
    return r.json(), None


def _http_error(code: int) -> str:
    if code == 404:
        return "Not found."
    if code == 422:
        return "Invalid input. Check the question and topic."
    return f"Server error ({code}). Please try again."


def stream_ask(payload: dict, on_event) -> tuple[dict | None, str | None]:
    """POST /ask/stream: calls on_event(ev) for every agent event, returns (result, error)."""
    try:
        with httpx.stream("POST", API_URL + "/ask/stream", json=payload, timeout=REQUEST_TIMEOUT) as r:
            if r.status_code >= 400:
                return None, _http_error(r.status_code)
            for line in r.iter_lines():
                if not line.strip():
                    continue
                msg = json.loads(line)
                if msg["type"] == "event":
                    on_event(msg["event"])
                elif msg["type"] == "result":
                    return msg["data"], None
                elif msg["type"] == "error":
                    return None, msg["message"]
    except httpx.ConnectError:
        return None, "The API is not running. Start it with: uvicorn app.api:app"
    except httpx.TimeoutException:
        return None, "The request timed out. Please try again."
    return None, "The answer stopped before it finished. Please try again."


def api_online() -> bool:
    try:
        return httpx.request("GET", API_URL + "/health", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


def age_label(published: date, today: date) -> str | None:
    """'Today' or 'Yesterday' for fresh news, otherwise None."""
    return {0: "Today", 1: "Yesterday"}.get((today - published).days)


def _domain(url: str) -> str:
    """Short link label: the site name instead of [1], [2]."""
    return urlparse(url).netloc.lower().removeprefix("www.") or "source"


def _md(text: str) -> str:
    """Escape '$' so Streamlit does not render LaTeX."""
    return text.replace("$", "\\$")


def _count(cards: list[dict], field: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in cards:
        out[c[field]] = out.get(c[field], 0) + 1
    return out


def split_bar(label: str, counts: dict[str, int], colors: dict[str, str]) -> str:
    """A single stacked bar with a legend, as HTML."""
    total = sum(counts.values()) or 1
    parts = "".join(
        f'<span style="width:{counts.get(k, 0) / total * 100:.1f}%;background:{c}"></span>' for k, c in colors.items()
    )
    legend = "".join(f'<span><i style="background:{c}"></i>{k} · {counts.get(k, 0)}</span>' for k, c in colors.items())
    return (
        f'<div class="split-label">{label}</div><div class="split-bar">{parts}</div>'
        f'<div class="split-legend">{legend}</div>'
    )


def report_markdown(data: dict, question: str | None) -> str:
    """Plain Markdown report of one result, for download."""
    lines = ["# News Impact Report", ""]
    if question:
        lines += [f"**Question:** {question}", ""]
    lines += [f"_Generated {datetime.now(IST).strftime('%d %b %Y, %H:%M')} IST_", ""]
    if data.get("summary"):
        lines += ["## Summary", ""]
        for p in data["summary"]:
            links = " ".join(f"[{_domain(u)}]({u})" for u in p["sources"])
            lines.append(f"- {p['text']} {links}")
        lines.append("")
    if data.get("cards"):
        lines += ["## News impact", ""]
        for c in data["cards"]:
            lines += [
                f"### [{c['title']}]({c['url']})",
                f"{c['source']} · {c['published_date']} · **{c['sentiment']}** · {c['level']} impact · {c['horizon']} term",
                "",
                c["summary"],
                "",
            ]
            if c.get("evidence"):
                lines += [f"> {c['evidence']}", ""]
            lines += [f"**Why:** {c['reason']}", ""]
            if c.get("also_reported_by"):
                lines += ["Also reported by: " + ", ".join(f"[{s['source']}]({s['url']})" for s in c["also_reported_by"]), ""]
    return "\n".join(lines)


def render_card(c: dict, i: int, today: date) -> None:
    with st.container(border=True, key=f"card-{c['sentiment']}-{i}"):
        st.markdown(f"**[{_md(c['title'])}]({c['url']})**")
        published = date.fromisoformat(c["published_date"])
        also = c.get("also_reported_by") or []
        more = f" · 🗞️ +{len(also)} more source{'s' if len(also) > 1 else ''}" if also else ""
        st.caption(f"🌐 {c['source']} · 📅 {published.strftime('%d %b %Y')}{more}")
        badges = [
            f":{SENTIMENT_COLOR[c['sentiment']]}-badge[{c['sentiment']}]",
            f":blue-badge[{c['level']} impact]",
            f":gray-badge[{c['horizon']} term]",
        ]
        fresh = age_label(published, today)
        if fresh:
            badges.append(f":orange-badge[{fresh}]")
        st.markdown(f"{SENTIMENT_ICON[c['sentiment']]} " + " ".join(badges))
        st.write(_md(c["summary"]))
        if c.get("evidence"):
            st.markdown(f"> **From the article:** “{_md(c['evidence'])}”")
        st.markdown(f"💡 **Why (analysis):** {_md(c['reason'])}")
        if also:
            links = " · ".join(f"[{s['source']}]({s['url']})" for s in also)
            st.markdown(f"🗞️ **Also reported by:** {links}")


def render_cards(cards: list[dict], key: str) -> None:
    """Impact cards with sentiment / level filters and sorting."""
    f1, f2, f3 = st.columns([4, 3, 2])
    sentiments = f1.pills(
        "Sentiment", list(SENTIMENT_COLOR), selection_mode="multi",
        default=list(SENTIMENT_COLOR), key=f"{key}-sent",
    )
    levels = f2.pills(
        "Impact level", list(LEVEL_RANK), selection_mode="multi",
        default=list(LEVEL_RANK), key=f"{key}-level",
    )
    sort = f3.selectbox("Sort by", ["Relevance", "Newest", "Highest impact"], key=f"{key}-sort")

    shown = [c for c in cards if c["sentiment"] in sentiments and c["level"] in levels]
    if sort == "Newest":
        shown.sort(key=lambda c: c["published_date"], reverse=True)
    elif sort == "Highest impact":
        shown.sort(key=lambda c: LEVEL_RANK[c["level"]])

    if not shown:
        st.info("No cards match these filters.")
        return
    st.caption(f"Showing {len(shown)} of {len(cards)} articles")
    today = datetime.now(IST).date()
    for i, c in enumerate(shown):
        render_card(c, i, today)


def render_result(data: dict, key: str = "ask", question: str | None = None) -> None:
    status = data["status"]
    if status == "error":
        st.error(data.get("message") or "Something went wrong.")
        return
    if status == "no_news":
        st.info(data.get("message") or "No relevant news found.")
        return
    if data.get("message"):
        st.warning(data["message"])

    cards = data["cards"]
    sent = _count(cards, "sentiment")
    levels = _count(cards, "level")
    today = datetime.now(IST).date()
    fresh = sum(1 for c in cards if age_label(date.fromisoformat(c["published_date"]), today))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📰 Articles", len(cards))
    m2.metric("📈 Positive", sent.get("positive", 0))
    m3.metric("📉 Negative", sent.get("negative", 0))
    m4.metric("🔥 High", levels.get("high", 0), help=f"{fresh} from today or yesterday")

    if data["summary"]:
        with st.container(key="summary"):
            st.subheader("✨ Summary")
            for p in data["summary"]:
                links = " ".join(f"[[{_domain(u)}]]({u})" for u in p["sources"])
                st.markdown(f"- {_md(p['text'])} {links}")

    if cards:
        with st.expander("📊 Impact breakdown", expanded=True):
            st.markdown(
                split_bar("Sentiment", sent, SENTIMENT_HEX)
                + split_bar("Impact level", levels, LEVEL_HEX)
                + split_bar("Time horizon", _count(cards, "horizon"), HORIZON_HEX),
                unsafe_allow_html=True,
            )

    st.subheader("🗞️ News impact")
    render_cards(cards, key)

    st.download_button(
        "⬇️ Download report (.md)",
        report_markdown(data, question),
        file_name=f"news-impact-{data.get('query_id', 'report')}.md",
        mime="text/markdown",
        key=f"{key}-download",
    )
    followup_section(data, key)


FOLLOWUP_IDEAS = [
    "Ispe mujhe kya karna chahiye?",
    "Which news matters most for my costs?",
    "Short term vs long term risk kya hai?",
]


def _pick_followup(pills_key: str, pending_key: str) -> None:
    st.session_state[pending_key] = st.session_state.get(pills_key)
    st.session_state[pills_key] = None


def followup_section(data: dict, key: str) -> None:
    """Chat about this result. Answers come only from its news cards, with sources."""
    qid = data.get("query_id")
    if not qid or not data.get("cards"):
        return
    store, pending = f"followups-{qid}", f"{key}-fu-pending"
    if store not in st.session_state:
        st.session_state[store] = list(data.get("followups") or [])

    with st.container(key=f"chat-{key}"):
        st.subheader("💬 Ask a follow-up")
        st.caption("Answers use only the news above, and link their sources.")
        for f in st.session_state[store]:
            with st.chat_message("user"):
                st.markdown(_md(f["question"]))
            with st.chat_message("assistant", avatar="☀️"):
                st.markdown(_md(f["answer"]))
                if f.get("sources"):
                    st.markdown("Sources: " + " ".join(f"[[{_domain(u)}]]({u})" for u in f["sources"]))
                if not f.get("grounded", True):
                    st.caption("⚠️ Not backed by the news above. Treat it with care.")

        st.pills(
            "Ideas", FOLLOWUP_IDEAS, key=f"{key}-fu-pills", label_visibility="collapsed",
            on_change=_pick_followup, args=(f"{key}-fu-pills", pending),
        )
        with st.form(f"{key}-fu-form", clear_on_submit=True, border=False):
            c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
            text = c1.text_input("Your follow-up", placeholder="e.g. Ispe mujhe kya karna chahiye?")
            sent = c2.form_submit_button("Ask ➤", use_container_width=True)

    ask = st.session_state.pop(pending, None) or (text.strip() if sent else "")
    if not ask:
        return
    with st.spinner("Thinking about it with the news above…"):
        answer, err = call_api("POST", "/followup", json={"query_id": qid, "question": ask})
    if err:
        st.error(err)
        return
    st.session_state[store].append(answer)
    st.rerun()


def _use_example() -> None:
    picked = st.session_state.get("example")
    if picked:
        st.session_state["question"] = picked


def ask_page() -> None:
    with st.container(key="hero"):
        st.markdown('<span class="hero-eyebrow">☀️ Solar business radar</span>', unsafe_allow_html=True)
        st.title("News Impact")
        st.caption("Ask about your business. Answers use only news from the last 30 days, with source links.")

    st.pills("💡 Try an example", EXAMPLE_QUESTIONS, key="example", on_change=_use_example)

    with st.form("ask"):
        question = st.text_area(
            "Your question",
            max_chars=500,
            height=110,
            key="question",
            placeholder="e.g. How will rising coal prices affect my module production cost?",
        )
        topic = st.selectbox("Topic", TOPICS)
        submitted = st.form_submit_button("🔍 Analyse impact", type="primary", use_container_width=True)

    if submitted:
        if not question.strip():
            st.warning("Please type a question.")
            return
        start = time.monotonic()
        board = agent_board.AgentBoard()
        with st.status("🤖 Agents are working on your question…", expanded=True) as status:
            canvas = st.empty()
            canvas.markdown(board.html(), unsafe_allow_html=True)

            def on_event(ev: dict) -> None:
                board.update(ev)
                canvas.markdown(board.html(), unsafe_allow_html=True)

            payload = {"question": question, "topic": topic}
            data, err = stream_ask(payload, on_event)
            seconds = time.monotonic() - start
            if err or data.get("status") == "error":
                status.update(label="⚠️ The agents could not finish", state="error", expanded=True)
            else:
                status.update(label=f"✅ Agents finished in {seconds:.0f}s", state="complete", expanded=False)
        if err:
            st.session_state.pop("last", None)
            st.error(err)
            return
        st.session_state["last"] = data
        st.session_state["last_question"] = question.strip()
        st.session_state["last_seconds"] = seconds
        st.session_state["last_board"] = board.html()
        st.toast(f"Done in {seconds:.0f}s", icon="✅")
    elif "last" in st.session_state and "last_board" in st.session_state:
        # Later reruns (filters, sorting) keep the agent trace one click away.
        with st.expander(f"🤖 How the agents worked ({st.session_state.get('last_seconds', 0):.0f}s)"):
            st.markdown(st.session_state["last_board"], unsafe_allow_html=True)

    if "last" in st.session_state:
        render_result(st.session_state["last"], "ask", st.session_state.get("last_question"))


def _ask_again(question: str) -> None:
    st.session_state["page"] = "Ask"
    st.session_state["question"] = question
    st.session_state.pop("last", None)
    st.session_state.pop("last_board", None)


def history_page() -> None:
    st.title("🕘 History")
    items, err = call_api("GET", "/history", params={"limit": 50})
    if err:
        st.error(err)
        return
    if not items:
        st.info("No questions yet.")
        return

    status_icon = {"ok": "✅", "no_news": "📭", "error": "⚠️"}
    search = st.text_input("Search past questions", placeholder="Type to filter...", key="history-search")
    if search.strip():
        items = [i for i in items if search.strip().lower() in i["question"].lower()]
        if not items:
            st.info("No past questions match your search.")
            return

    labels = {
        i["query_id"]: f"{status_icon.get(i['status'], '•')} {i['created_at'][:16].replace('T', ' ')} · {i['question'][:80]}"
        for i in items
    }
    query_id = st.selectbox("Past questions", list(labels), format_func=labels.get)
    question = next(i["question"] for i in items if i["query_id"] == query_id)

    run, err = call_api("GET", f"/history/{query_id}")
    if err:
        st.error(err)
        return

    c1, c2 = st.columns([5, 1.4], vertical_alignment="center")
    c1.markdown(f"#### “{_md(question)}”")
    c2.button("🔁 Ask again", on_click=_ask_again, args=(question,), use_container_width=True)
    render_result(run, f"history-{query_id}", question)


def sidebar() -> str:
    with st.sidebar:
        st.markdown("## ☀️ News Impact")
        st.caption("AI agents that read the news for your solar business.")
        page = st.radio("Page", list(PAGES), key="page", format_func=PAGES.get)
        st.divider()

        online = api_online()
        color, text = ("#16a34a", "API online") if online else ("#dc2626", "API offline")
        st.markdown(f'<span class="status-dot" style="background:{color}"></span>{text}', unsafe_allow_html=True)

        with st.expander("🏭 Business profile"):
            st.markdown(f"**{BUSINESS}**  \n📍 {LOCATION}")
            st.markdown("**Products**\n" + "\n".join(f"- {p}" for p in PRODUCTS))
            st.markdown("**Watching**\n" + "\n".join(f"- {d}" for d in DEPENDENCIES))
        st.caption("News window: last 30 days · Sources linked on every point")
    return page


def main() -> None:
    st.set_page_config(page_title="News Impact", page_icon="☀️", layout="wide")
    st.markdown(CSS + agent_board.CSS, unsafe_allow_html=True)
    page = sidebar()
    # A plain if/else: a bare expression would make Streamlit print its value ("None").
    if page == "Ask":
        ask_page()
    elif page == "Trends":
        trends_page(call_api)
    else:
        history_page()


if __name__ == "__main__":
    main()
