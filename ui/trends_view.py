"""Trends page: how the mood of the saved news changes over time and by theme."""

import html
from datetime import datetime
from typing import Callable

import streamlit as st

RANGES = {7: "Last week", 30: "Last month", 90: "Last 3 months"}
DIRECTION = {
    "worse": ("📉 Getting worse", "worse"),
    "better": ("📈 Getting better", "better"),
    "steady": ("➖ Steady", "steady"),
    "new": ("✨ New topic", "new"),
    "quiet": ("💤 Quiet lately", "quiet"),
}

CSS = """
<style>
.mood { border-radius: 20px; padding: 1.3rem 1.6rem; color: #fff; display: flex; align-items: center; gap: 1.4rem;
        box-shadow: 0 10px 30px rgba(0,0,0,.12); }
.mood .big { font-size: 3.2rem; line-height: 1; }
.mood .score { font-size: 2.4rem; font-weight: 800; line-height: 1.1; }
.mood .label { font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; opacity: .9; font-weight: 700; }
.mood .sub { font-size: .92rem; opacity: .95; margin-top: .3rem; }
.hl { border-left: 4px solid #f59e0b; background: rgba(245,158,11,.08); padding: .55rem .9rem;
      border-radius: 0 10px 10px 0; margin: .35rem 0; font-size: .92rem; }
.theme { border: 1px solid rgba(128,128,128,.25); border-radius: 16px; padding: .9rem 1rem; margin-bottom: .8rem;
         transition: transform .15s ease, box-shadow .15s ease; }
.theme:hover { transform: translateY(-2px); box-shadow: 0 10px 24px rgba(0,0,0,.08); }
.theme .top { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
.theme .tname { font-weight: 800; font-size: 1.02rem; }
.chip { font-size: .75rem; font-weight: 700; padding: .15rem .55rem; border-radius: 999px; white-space: nowrap; }
.chip.worse { background: rgba(220,38,38,.12); color: #dc2626; }
.chip.better { background: rgba(22,163,74,.12); color: #16a34a; }
.chip.steady { background: rgba(100,116,139,.15); color: #64748b; }
.chip.new { background: rgba(99,102,241,.14); color: #6366f1; }
.chip.quiet { background: rgba(100,116,139,.1); color: #94a3b8; }
.dbar { position: relative; height: 10px; border-radius: 999px; background: rgba(128,128,128,.15); margin: .7rem 0 .35rem; }
.dbar::after { content: ""; position: absolute; left: 50%; top: -3px; bottom: -3px; width: 2px; background: rgba(128,128,128,.55); }
.dbar span { position: absolute; top: 0; bottom: 0; border-radius: 999px; }
.theme .meta { display: flex; justify-content: space-between; gap: .5rem; font-size: .78rem; opacity: .75; flex-wrap: wrap; }
.theme .latest { font-size: .83rem; margin-top: .45rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bars { display: flex; align-items: flex-end; gap: 2px; border-bottom: 1px solid rgba(128,128,128,.35);
        background: repeating-linear-gradient(to top, transparent 0 49px, rgba(128,128,128,.12) 49px 50px); }
.bars .col { flex: 1; height: 100%; display: flex; flex-direction: column-reverse; min-width: 3px; }
.bars .col span { display: block; width: 100%; border-radius: 3px 3px 0 0; transition: filter .15s; }
.bars .col:hover span { filter: brightness(1.15); }
.xl { display: flex; font-size: .68rem; opacity: .6; margin-top: .25rem; }
.xl span { flex: 1; white-space: nowrap; overflow: visible; }
.mline { width: 100%; display: block; border-bottom: 1px solid rgba(128,128,128,.35); }
.mwrap { display: flex; gap: 4px; }
.yl { position: relative; width: 30px; flex: none; font-size: .66rem; opacity: .55; text-align: right; }
.yl span { position: absolute; right: 0; }
</style>
"""


def mood(score: int | None) -> tuple[str, str, str]:
    """(emoji, label, background) for a mood score from -100 to +100."""
    if score is None:
        return "😶", "No data", "linear-gradient(135deg,#64748b,#94a3b8)"
    if score >= 25:
        return "😄", "Positive", "linear-gradient(135deg,#15803d,#22c55e)"
    if score <= -25:
        return "😟", "Negative", "linear-gradient(135deg,#b91c1c,#f97316)"
    return "😐", "Mixed", "linear-gradient(135deg,#b45309,#f59e0b)"


def fmt(score: int | None) -> str:
    return "–" if score is None else f"{score:+d}"


def theme_card(t: dict) -> str:
    chip, cls = DIRECTION[t["direction"]]
    sc = t["score"] or 0
    color = "#16a34a" if sc > 0 else "#dc2626" if sc < 0 else "#94a3b8"
    left, width = (50, sc / 2) if sc >= 0 else (50 + sc / 2, -sc / 2)
    latest = t["latest"]
    dot = {"positive": "🟢", "negative": "🔴"}.get(latest["sentiment"], "⚪")
    return (
        f'<div class="theme"><div class="top"><span class="tname">{html.escape(t["theme"])}</span>'
        f'<span class="chip {cls}">{chip}</span></div>'
        f'<div class="dbar"><span style="left:{left:.0f}%;width:{max(width, 1.5):.0f}%;background:{color}"></span></div>'
        f'<div class="meta"><span>mood <b>{fmt(t["score"])}</b> · {t["count"]} articles</span>'
        f'<span>earlier {fmt(t["earlier_score"])} → recent {fmt(t["recent_score"])}</span></div>'
        f'<div class="meta"><span>🟢 {t["positive"]} &nbsp;🔴 {t["negative"]} &nbsp;⚪ {t["neutral"]}</span></div>'
        f'<div class="latest">{dot} <a href="{html.escape(latest["url"])}" target="_blank">'
        f'{html.escape(latest["title"])}</a></div></div>'
    )


# Charts are plain HTML/SVG: Streamlit's own charts need pyarrow, which needs NumPy 2,
# and the pinned LangChain stack keeps NumPy 1 on this machine.
CHART_H = 200
SENT_COLORS = (("negative", "#dc2626"), ("neutral", "#94a3b8"), ("positive", "#16a34a"))


def _day_label(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d %b")


def daily_bars(daily: list[dict]) -> str:
    """Stacked bars, one per day: negative at the bottom, positive on top."""
    top = max((sum(d[s] for s, _ in SENT_COLORS) for d in daily), default=0) or 1
    every = max(1, len(daily) // 6)
    bars, labels = [], []
    for i, d in enumerate(daily):
        parts = "".join(
            f'<span style="height:{d[s] / top * 100:.1f}%;background:{c}"></span>' for s, c in SENT_COLORS if d[s]
        )
        tip = f'{_day_label(d["date"])}: {d["positive"]} positive, {d["negative"]} negative, {d["neutral"]} neutral'
        bars.append(f'<div class="col" title="{tip}">{parts}</div>')
        labels.append(f'<span>{_day_label(d["date"]) if i % every == 0 or i == len(daily) - 1 else ""}</span>')
    legend = "".join(f'<span><i style="background:{c}"></i>{s}</span>' for s, c in reversed(SENT_COLORS))
    return (
        f'<div class="bars" style="height:{CHART_H}px">{"".join(bars)}</div>'
        f'<div class="xl">{"".join(labels)}</div><div class="split-legend">{legend}</div>'
    )


def rolling_mood(daily: list[dict], window: int) -> list[tuple[str, int | None]]:
    """(date, mood score) using the last `window` days up to each day; None with no news."""
    out = []
    for i, d in enumerate(daily):
        span = daily[max(0, i - window + 1): i + 1]
        pos, neg = sum(x["positive"] for x in span), sum(x["negative"] for x in span)
        total = pos + neg + sum(x["neutral"] for x in span)
        out.append((d["date"], round((pos - neg) / total * 100) if total else None))
    return out


def mood_line(points: list[tuple[str, int | None]]) -> str:
    """SVG line of the mood score with a zero line; gaps where there was no news."""
    w, h, pad = 600, CHART_H, 14
    n = max(len(points) - 1, 1)

    def xy(i: int, v: int) -> tuple[float, float]:
        return i / n * w, pad + (100 - v) / 200 * (h - 2 * pad)

    segments, seg, dots = [], [], []
    for i, (day, v) in enumerate(points):
        if v is None:
            if seg:
                segments.append(seg)
            seg = []
            continue
        x, y = xy(i, v)
        seg.append(f"{x:.1f},{y:.1f}")
        color = "#16a34a" if v > 0 else "#dc2626" if v < 0 else "#94a3b8"
        # A zero-length round-capped line with a non-scaling stroke stays a circle when the SVG stretches.
        dots.append(
            f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="7" '
            f'stroke-linecap="round" vector-effect="non-scaling-stroke"><title>{_day_label(day)}: {v:+d}</title></line>'
        )
    if seg:
        segments.append(seg)
    lines = "".join(
        f'<polyline points="{" ".join(s)}" fill="none" stroke="#ea580c" stroke-width="2.5" '
        f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>' for s in segments
    )
    zero = xy(0, 0)[1]
    grid = (
        f'<rect x="0" y="{pad}" width="{w}" height="{zero - pad:.1f}" fill="rgba(22,163,74,.07)"/>'
        f'<rect x="0" y="{zero:.1f}" width="{w}" height="{h - pad - zero:.1f}" fill="rgba(220,38,38,.07)"/>'
        f'<line x1="0" x2="{w}" y1="{zero:.1f}" y2="{zero:.1f}" stroke="rgba(128,128,128,.6)" '
        f'stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>'
    )
    every = max(1, len(points) // 6)
    labels = "".join(
        f'<span>{_day_label(d) if i % every == 0 or i == len(points) - 1 else ""}</span>' for i, (d, _) in enumerate(points)
    )
    axis = (
        f'<span style="top:{pad - 7}px">+100</span><span style="top:{zero - 7:.0f}px">0</span>'
        f'<span style="top:{h - pad - 7}px">−100</span>'
    )
    return (
        f'<div class="mwrap"><div class="yl">{axis}</div>'
        f'<svg class="mline" viewBox="0 0 {w} {h}" preserveAspectRatio="none" style="height:{h}px">'
        f'{grid}{lines}{"".join(dots)}</svg></div>'
        f'<div class="xl" style="padding-left:34px">{labels}</div>'
    )


def trends_page(call_api: Callable) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("📈 Trends")
    st.caption("How the mood of your news is changing, built from every question you have asked.")
    days = st.segmented_control("Range", list(RANGES), default=30, format_func=RANGES.get, key="trend-days") or 30
    data, err = call_api("GET", "/trends", params={"days": days})
    if err:
        st.error(err)
        return
    if not data["total"]:
        st.info("No saved news in this period yet. Ask a few questions and come back here.")
        return

    o = data["overall"]
    emoji, label, bg = mood(o["score"])
    st.markdown(
        f'<div class="mood" style="background:{bg}"><div class="big">{emoji}</div>'
        f'<div><div class="label">Overall mood · {RANGES[days].lower()}</div>'
        f'<div class="score">{fmt(o["score"])} <span style="font-size:1.1rem;font-weight:600">{label}</span></div>'
        f'<div class="sub">{DIRECTION[o["direction"]][0]} · first half {fmt(o["earlier_score"])}'
        f' → second half {fmt(o["recent_score"])}</div></div></div>',
        unsafe_allow_html=True,
    )
    st.write("")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📰 News analysed", data["total"])
    m2.metric("📈 Positive", o["positive"])
    m3.metric("📉 Negative", o["negative"])
    m4.metric("➖ Neutral", o["neutral"])

    if data["highlights"]:
        st.subheader("🔥 What changed")
        for h in data["highlights"]:
            st.markdown(f'<div class="hl">{html.escape(h)}</div>', unsafe_allow_html=True)

    window = 3 if days <= 7 else 7
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**News per day, by sentiment**")
        st.markdown(daily_bars(data["daily"]), unsafe_allow_html=True)
    with c2:
        st.markdown(f"**Mood score, {window}-day rolling** (−100 to +100)")
        st.markdown(mood_line(rolling_mood(data["daily"], window)), unsafe_allow_html=True)

    if data["themes"]:
        st.subheader("🧭 Themes")
        st.caption("Bar: left of the middle is negative, right is positive. Getting worse/better compares the two halves of the range.")
        cols = st.columns(2)
        for i, t in enumerate(data["themes"]):
            cols[i % 2].markdown(theme_card(t), unsafe_allow_html=True)
