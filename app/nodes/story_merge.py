"""Group articles that report the same story on different sites (pure code, no LLM)."""

import re
from datetime import date
from difflib import SequenceMatcher

MAX_DAYS_APART = 2      # the same story is published within a couple of days
MIN_SHARED_WORDS = 3
MIN_JACCARD = 0.7       # share of title words in common (0.58 merged two different brokers)
MIN_RATIO = 0.8         # near-identical wording

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set(
    "the a an and or of to in on for at by with from as is are was were be its it this that "
    "after over amid into says said new news latest update updates today india indian".split()
)
# "Coal prices rise - The Economic Times" / "... | Mint": drop a short site name at the end.
_SITE_SUFFIX = re.compile(r"\s+[-|–—]\s+[^-|–—]{1,40}$")


def _clean(title: str) -> str:
    return _SITE_SUFFIX.sub("", title.strip()).lower()


def _words(title: str) -> set[str]:
    return {w for w in _WORD.findall(_clean(title)) if w not in _STOP and len(w) > 2}


def same_story(title_a: str, date_a: date, title_b: str, date_b: date) -> bool:
    """True when two headlines very likely report the same event."""
    if abs((date_a - date_b).days) > MAX_DAYS_APART:
        return False
    a, b = _words(title_a), _words(title_b)
    shared = a & b
    if len(shared) >= MIN_SHARED_WORDS and len(shared) / len(a | b) >= MIN_JACCARD:
        return True
    return SequenceMatcher(None, _clean(title_a), _clean(title_b)).ratio() >= MIN_RATIO


def group_stories(items: list, key) -> list[list]:
    """Group items (already in rank order) into stories. The first item of each group is the
    best ranked one and becomes the card; `key(item)` returns (title, date)."""
    groups: list[list] = []
    for item in items:
        title, d = key(item)
        for g in groups:
            lead_title, lead_date = key(g[0])
            if same_story(title, d, lead_title, lead_date):
                g.append(item)
                break
        else:
            groups.append([item])
    return groups
