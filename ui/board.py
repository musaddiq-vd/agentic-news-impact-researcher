"""Live agent board: turns streamed agent events into an animated pipeline view."""

import html

STEPS = [
    ("query_builder", "🧠", "Query builder"),
    ("search_1", "🔎", "Search agent 1"),
    ("search_2", "🔎", "Search agent 2"),
    ("search_3", "🔎", "Search agent 3"),
    ("merge", "🔗", "Merge"),
    ("filter_rank", "📊", "Filter & rank"),
    ("impact_analyzer", "⚡", "Impact analyzer"),
    ("summarizer", "✍️", "Summarizer"),
    ("validator", "🛡️", "Validator"),
]
STATE_LABEL = {"pending": "waiting", "running": "working…", "done": "✔ done", "error": "✖ failed", "skipped": "skipped"}
FEED_MARK = {"start": ("▶", "run"), "done": ("✔", "ok"), "info": ("•", ""), "warn": ("!", "run"), "error": ("✖", "bad")}

CSS = """
<style>
.pipe { display: flex; flex-direction: column; gap: .45rem; }
.pipe-row { display: flex; gap: .45rem; flex-wrap: wrap; }
.pipe-row .pipe-step { min-width: 180px; }
.pipe-step {
  flex: 1; display: flex; align-items: center; gap: .6rem; padding: .55rem .8rem;
  border-radius: 12px; border: 1px solid rgba(128,128,128,.25); background: rgba(128,128,128,.05);
  font-size: .88rem; min-width: 0; transition: all .25s ease;
}
.pipe-step .ico { font-size: 1.15rem; }
.pipe-step .name { font-weight: 700; white-space: nowrap; }
.pipe-step .note { opacity: .75; font-size: .8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pipe-step .state { margin-left: auto; font-size: .8rem; white-space: nowrap; }
.pipe-step.pending { opacity: .45; }
.pipe-step.running { border-color: #f59e0b; background: rgba(245,158,11,.12); animation: pipe-pulse 1.2s ease-in-out infinite; }
.pipe-step.done { border-color: rgba(22,163,74,.55); background: rgba(22,163,74,.08); }
.pipe-step.error { border-color: #dc2626; background: rgba(220,38,38,.08); }
.pipe-step.skipped { opacity: .35; border-style: dashed; }
@keyframes pipe-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245,158,11,.45); }
  50% { box-shadow: 0 0 0 6px rgba(245,158,11,0); }
}
.pipe-bar { height: 5px; border-radius: 999px; background: rgba(128,128,128,.2); overflow: hidden; margin-top: .25rem; }
.pipe-bar span { display: block; height: 100%; background: linear-gradient(90deg,#f59e0b,#ea580c); transition: width .3s ease; }
.pipe-par-label { font-size: .72rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; opacity: .55; margin: .15rem 0 -.2rem .2rem; }
.feed {
  margin-top: .8rem; font-family: ui-monospace, Consolas, monospace; font-size: .78rem; line-height: 1.55;
  background: rgba(15,23,42,.94); color: #e2e8f0; border-radius: 12px; padding: .7rem .9rem; overflow-x: auto;
}
.feed div { white-space: nowrap; }
.feed .t { color: #64748b; } .feed .ok { color: #4ade80; } .feed .run { color: #fbbf24; } .feed .bad { color: #f87171; }
.feed .ag { color: #93c5fd; }
</style>
"""


class AgentBoard:
    """Keeps every agent's state from the streamed events and draws it as HTML."""

    def __init__(self) -> None:
        self.steps = {key: {"state": "pending", "note": ""} for key, _, _ in STEPS}
        self.progress: tuple[int, int] | None = None
        self.feed: list[dict] = []

    def update(self, ev: dict) -> None:
        self.feed.append(ev)
        step = self.steps.get(ev.get("agent"))
        if step is None:
            return
        kind, msg = ev.get("event"), ev.get("message", "")
        if kind == "start":
            step.update(state="running", note=msg)
            if ev.get("total"):
                self.progress = (0, ev["total"])
        elif kind == "done":
            ms = ev.get("ms")
            step.update(state="done", note=msg + (f" · {ms / 1000:.1f}s" if ms is not None else ""))
        elif kind == "error":
            step.update(state="error", note=msg)
        elif kind == "info" and "skipping" in msg:
            step.update(state="skipped", note="no query to run")
        else:
            step["note"] = msg
            if ev.get("total"):
                self.progress = (ev.get("done", 0), ev["total"])

    def _step(self, key: str, icon: str, name: str) -> str:
        s = self.steps[key]
        bar = ""
        if key == "impact_analyzer" and self.progress and s["state"] in ("running", "done"):
            done, total = self.progress
            pct = 100 if s["state"] == "done" else done / max(total, 1) * 100
            bar = f'<div class="pipe-bar"><span style="width:{pct:.0f}%"></span></div>'
        note = html.escape(s["note"]) or "&nbsp;"
        return (
            f'<div class="pipe-step {s["state"]}"><span class="ico">{icon}</span>'
            f'<div style="min-width:0;flex:1"><div class="name">{name}</div>'
            f'<div class="note" title="{note}">{note}</div>{bar}</div>'
            f'<span class="state">{STATE_LABEL[s["state"]]}</span></div>'
        )

    def html(self) -> str:
        by_key = {k: (k, i, n) for k, i, n in STEPS}
        rows = [self._step(*by_key["query_builder"])]
        rows.append('<div class="pipe-par-label">⚡ 3 search agents in parallel</div>')
        searches = "".join(self._step(*by_key[f"search_{i}"]) for i in (1, 2, 3))
        rows.append(f'<div class="pipe-row">{searches}</div>')
        rows += [self._step(*by_key[k]) for k in ("merge", "filter_rank", "impact_analyzer", "summarizer", "validator")]
        feed = []
        for ev in self.feed[-8:]:
            mark, cls = FEED_MARK.get(ev.get("event"), ("•", ""))
            feed.append(
                f'<div><span class="t">{ev.get("t", 0):6.2f}s</span> '
                f'<span class="ag">{html.escape(ev.get("agent", "")).ljust(15).replace(" ", "&nbsp;")}</span> '
                f'<span class="{cls}">{mark}</span> {html.escape(ev.get("message", ""))}</div>'
            )
        return f'<div class="pipe">{"".join(rows)}</div><div class="feed">{"".join(feed) or "starting…"}</div>'
