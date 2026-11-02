"""Live agent events.

Every agent step calls `emit()`. Each event is printed as a colored line in the terminal
and, when a listener is set (the streaming API), passed on so the UI can show live progress.
Set TRACE_LOGS=0 in .env to turn the terminal lines off.
"""

import os
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

Listener = Callable[[dict], None]

_listener: ContextVar[Listener | None] = ContextVar("trace_listener", default=None)
_run_start: ContextVar[float | None] = ContextVar("trace_run_start", default=None)
_print_lock = threading.Lock()

# agent -> (icon, ANSI color)
AGENTS = {
    "run": ("🚀", "97"),
    "query_builder": ("🧠", "95"),
    "search_1": ("🔎", "96"),
    "search_2": ("🔎", "94"),
    "search_3": ("🔎", "36"),
    "merge": ("🔗", "37"),
    "filter_rank": ("📊", "93"),
    "impact_analyzer": ("⚡", "33"),
    "summarizer": ("✍️ ", "92"),
    "validator": ("🛡️ ", "32"),
}
MARKS = {"start": ("▶", "2"), "done": ("✔", "92"), "info": ("•", "2"), "warn": ("!", "93"), "error": ("✖", "91")}


def _enable_windows_colors() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-12)  # stderr
        mode = ctypes.c_uint32()
        if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


_enable_windows_colors()


def _enabled() -> bool:
    return os.getenv("TRACE_LOGS", "1") != "0"


def _color(code: str, text: str) -> str:
    use = sys.stderr.isatty() and not os.getenv("NO_COLOR")
    return f"\033[{code}m{text}\033[0m" if use else text


def _write(line: str) -> None:
    with _print_lock:
        try:
            print(line, file=sys.stderr, flush=True)
        except UnicodeEncodeError:  # a non-UTF-8 console or log file
            print(line.encode("ascii", "replace").decode(), file=sys.stderr, flush=True)


def _elapsed() -> float:
    start = _run_start.get()
    return round(time.monotonic() - start, 2) if start is not None else 0.0


def _print_event(ev: dict) -> None:
    icon, color = AGENTS.get(ev["agent"], ("•", "37"))
    mark, mark_color = MARKS.get(ev["event"], ("•", "37"))
    ms = ev.get("ms")
    took = " " + _color("2", f"({ms / 1000:.2f}s)") if ms is not None else ""
    clock = _color("2", f"{ev['t']:6.2f}s")
    name = _color(color + ";1", ev["agent"].ljust(15))
    _write(f"{_color('2', '│')} {clock}  {icon} {name} {_color(mark_color, mark)} {ev['message']}{took}")


def emit(agent: str, event: str, message: str, **data) -> dict:
    """Record one event: event is start, done, info, warn or error."""
    ev = {"agent": agent, "event": event, "message": message, "t": _elapsed(), **data}
    if _enabled():
        _print_event(ev)
    listener = _listener.get()
    if listener:
        try:
            listener(ev)
        except Exception:
            pass  # a broken listener must never break the run
    return ev


@contextmanager
def step(agent: str, message: str, **data) -> Iterator[dict]:
    """Emit start, run the block, emit done with its duration.

    The block may set `done` (message) and extra fields on the yielded dict.
    """
    info: dict = {"done": "done"}
    t0 = time.monotonic()
    emit(agent, "start", message, **data)
    try:
        yield info
    except Exception as exc:
        emit(agent, "error", f"failed: {exc}"[:200], ms=round((time.monotonic() - t0) * 1000))
        raise
    done = info.pop("done")
    emit(agent, "done", done, ms=round((time.monotonic() - t0) * 1000), **info)


@contextmanager
def listen(listener: Listener) -> Iterator[None]:
    """Send every event emitted in this context (and threads copied from it) to `listener`."""
    token = _listener.set(listener)
    try:
        yield
    finally:
        _listener.reset(token)


@contextmanager
def run(question: str) -> Iterator[dict]:
    """Wrap one whole run: a header line, the timer every event uses, and a footer line."""
    token = _run_start.set(time.monotonic())
    outcome: dict = {"status": "error"}
    if _enabled():
        q = question if len(question) <= 70 else question[:67] + "..."
        _write(_color("2", "╭─") + " 🚀 " + _color("97;1", "New run") + _color("2", " · ") + f"“{q}”")
    try:
        yield outcome
    finally:
        if _enabled():
            icon = {"ok": "✅", "no_news": "📭"}.get(outcome["status"], "⚠️ ")
            _write(
                _color("2", "╰─") + f" {icon} " + _color("97;1", outcome["status"])
                + _color("2", f" in {_elapsed():.2f}s")
            )
        _run_start.reset(token)
