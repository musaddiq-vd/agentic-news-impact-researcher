"""Streamlit UI. Talks only to the FastAPI backend; never touches the graph or the DB."""

import os
import sys
from datetime import date, datetime
from pathlib import Path

import httpx
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # makes `app` importable

from app.config import IST  # noqa: E402
from app.profile import COMPETITORS, TOPICS  # noqa: E402

load_dotenv()
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT = 150  # /ask can take up to a minute or two

SENTIMENT_COLOR = {"positive": "green", "negative": "red", "neutral": "gray"}


def call_api(method: str, path: str, **kwargs) -> tuple[object | None, str | None]:
    """Return (json, None) on success or (None, user-friendly error)."""
    try:
        r = httpx.request(method, API_URL + path, timeout=REQUEST_TIMEOUT, **kwargs)
    except httpx.ConnectError:
        return None, "The API is not running. Start it with: uvicorn app.api:app"
    except httpx.TimeoutException:
        return None, "The request timed out. Please try again."
    if r.status_code == 404:
        return None, "Not found."
    if r.status_code == 422:
        return None, "Invalid input. Check the question, topic and competitors."
    if r.status_code >= 400:
        return None, f"Server error ({r.status_code}). Please try again."
    return r.json(), None


def age_label(published: date, today: date) -> str | None:
    """'Today' or 'Yesterday' for fresh news, otherwise None."""
    return {0: "Today", 1: "Yesterday"}.get((today - published).days)


def _md(text: str) -> str:
    """Escape '$' so Streamlit does not render LaTeX."""
    return text.replace("$", "\\$")


def render_result(data: dict) -> None:
    status = data["status"]
    if status == "error":
        st.error(data.get("message") or "Something went wrong.")
        return
    if status == "no_news":
        st.info(data.get("message") or "No relevant news found.")
        return
    if data.get("message"):
        st.warning(data["message"])

    if data["summary"]:
        st.subheader("Summary")
        for p in data["summary"]:
            links = " ".join(f"[[{i}]]({u})" for i, u in enumerate(p["sources"], start=1))
            st.markdown(f"- {_md(p['text'])} {links}")

    st.subheader("News impact")
    today = datetime.now(IST).date()
    for c in data["cards"]:
        with st.container(border=True):
            st.markdown(f"**[{_md(c['title'])}]({c['url']})**")
            published = date.fromisoformat(c["published_date"])
            st.caption(f"{c['source']} · {published.isoformat()}")
            badges = [
                f":{SENTIMENT_COLOR[c['sentiment']]}-badge[{c['sentiment']}]",
                f":blue-badge[{c['level']} impact]",
                f":gray-badge[{c['horizon']} term]",
            ]
            fresh = age_label(published, today)
            if fresh:
                badges.append(f":orange-badge[{fresh}]")
            st.markdown(" ".join(badges))
            st.write(_md(c["summary"]))
            st.markdown(f"**Why:** {_md(c['reason'])}")


def ask_page() -> None:
    st.title("News Impact")
    st.caption("Ask about your business. Answers use only news from the last 30 days, with source links.")
    with st.form("ask"):
        question = st.text_area(
            "Your question",
            max_chars=500,
            height=100,
            placeholder="e.g. How will rising coal prices affect my module production cost?",
        )
        topic = st.selectbox("Topic", TOPICS)
        competitors = st.multiselect("Competitors (optional)", COMPETITORS)
        submitted = st.form_submit_button("Ask")

    if submitted:
        if not question.strip():
            st.warning("Please type a question.")
            return
        with st.spinner("Searching news and analysing impact. This can take up to a minute..."):
            data, err = call_api(
                "POST", "/ask",
                json={"question": question, "topic": topic, "competitors": competitors},
            )
        if err:
            st.session_state.pop("last", None)
            st.error(err)
            return
        st.session_state["last"] = data

    if "last" in st.session_state:
        render_result(st.session_state["last"])


def history_page() -> None:
    st.title("History")
    items, err = call_api("GET", "/history", params={"limit": 20})
    if err:
        st.error(err)
        return
    if not items:
        st.info("No questions yet.")
        return
    labels = {
        i["query_id"]: f"{i['created_at'][:16].replace('T', ' ')} · {i['status']} · {i['question'][:80]}"
        for i in items
    }
    query_id = st.selectbox("Past questions", list(labels), format_func=labels.get)
    run, err = call_api("GET", f"/history/{query_id}")
    if err:
        st.error(err)
        return
    render_result(run)


def main() -> None:
    st.set_page_config(page_title="News Impact", page_icon="📰")
    page = st.sidebar.radio("Page", ["Ask", "History"])
    # A plain if/else: a bare expression would make Streamlit print its value ("None").
    if page == "Ask":
        ask_page()
    else:
        history_page()


if __name__ == "__main__":
    main()
