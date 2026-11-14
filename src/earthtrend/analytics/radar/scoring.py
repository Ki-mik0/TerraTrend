"""``radar_score`` and novelty against the previous run (docs/PLAN_ANALYTICS.md section 9.3).

radar_score = strength x (1 - q_global) x area_term + bonuses, where
area_term = log(1 + area_km2) / log(1 + max area in the run) (in 0..1; the ``norm`` of 9.3).
A region without an area gets the median area term of the run (1 if no area is known).
Bonuses (strength points): ``split_flag``, ``accelerating`` with statistics=pass, a new
recent change point.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from earthtrend.analytics.radar.models import Novelty, RadarEntry, RadarOptions

VERDICT_RANK = {
    "inadmissible": 0,
    "no_evidence": 1,
    "suspicious": 2,
    "likely": 3,
    "strong": 4,
    "proven": 5,
}
BREAKPOINT_SAME_MONTHS = 12  # a change point within a year of the previous one is not new


def _area_terms(entries: Sequence[RadarEntry]) -> list[float]:
    areas = [e.candidate.region_area_km2 for e in entries]
    known = [a for a in areas if a is not None and a > 0]
    if not known:
        return [1.0] * len(entries)
    norm = math.log1p(max(known))
    terms = [math.log1p(a) / norm if a is not None and a > 0 else None for a in areas]
    fill = float(np.median([t for t in terms if t is not None]))
    return [fill if t is None else t for t in terms]


def score_entries(entries: Sequence[RadarEntry], options: RadarOptions | None = None) -> None:
    """Sets ``radar_score`` and ``score_parts`` in place."""
    opts = options or RadarOptions()
    for e, area in zip(entries, _area_terms(entries), strict=True):
        q = e.candidate.q_global if e.candidate.q_global is not None else 1.0
        base = e.strength * (1.0 - q) * area
        parts = {"base": base, "area_term": area, "q_global": q}
        if e.split_flag:
            parts["split"] = opts.bonus_split
        if e.shape == "accelerating" and e.items.get("statistics") == "pass":
            parts["accelerating"] = opts.bonus_accelerating
        if e.new_breakpoint:
            parts["new_breakpoint"] = opts.bonus_new_breakpoint
        bonus = sum(v for k, v in parts.items() if k not in ("base", "area_term", "q_global"))
        e.radar_score = round(base + bonus, 4)
        e.score_parts = {k: round(v, 4) for k, v in parts.items()}


def _novelty(verdict: str, previous: str | None) -> Novelty:
    if previous is None:
        return "new"
    d = VERDICT_RANK[verdict] - VERDICT_RANK[previous]
    return "upgraded" if d > 0 else "downgraded" if d < 0 else "unchanged"


def apply_novelty(
    entries: Sequence[RadarEntry],
    previous: Sequence[RadarEntry] | None,
    options: RadarOptions | None = None,
) -> list[str]:
    """Sets ``novelty``, ``previous_verdict`` and clears ``new_breakpoint`` when the previous
    run already had a change point within a year. Returns previous keys not seen now."""
    if previous is None:
        for e in entries:
            e.novelty = "new"
        return []
    prev = {p.key: p for p in previous}
    for e in entries:
        p = prev.get(e.key)
        e.previous_verdict = p.verdict if p else None
        e.novelty = _novelty(e.verdict, e.previous_verdict)
        if p is not None and e.recent_breakpoint is not None:
            at = e.recent_breakpoint.at
            old = [cp.at for cp in p.changepoints]
            if p.recent_breakpoint is not None:
                old.append(p.recent_breakpoint.at)
            if any(
                abs((at.year - o.year) * 12 + at.month - o.month) <= BREAKPOINT_SAME_MONTHS
                for o in old
            ):
                e.new_breakpoint = False
    now = {e.key for e in entries}
    return sorted(k for k in prev if k not in now)


__all__ = ["VERDICT_RANK", "apply_novelty", "score_entries"]
