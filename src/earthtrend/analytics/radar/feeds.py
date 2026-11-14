"""Radar feeds (docs/PLAN_ANALYTICS.md section 9.4).

| feed | rule |
|---|---|
| strongest | ``proven`` / ``strong``, by radar_score |
| opposite | same variable and season: significant + and - (stage 1 FDR within the variable)
|            | in regions of one ``region_group``, or ``split_flag`` |
| accelerating | spline shape ``accelerating`` and statistics = pass |
| breakpoints | change point with probability > 0.7 in the last 5 years, no sensor event |
| almost | ``suspicious`` and years_to_detect_remaining <= 10 |
| stable | ``no_evidence``, CI contains 0 and both bounds within 0.2 sigma_anom per decade |
| ai_flagged | statistics significant, M1 sees a step (P(step) + P(trend_plus_step) >= 0.5) |

``ai_flagged`` is empty without M1. Every feed is ordered by radar_score (entries arrive
sorted), except ``stable`` (narrowest CI first) and ``breakpoints`` (latest first).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from earthtrend.analytics.radar.models import (
    FEED_NAMES,
    RadarCandidate,
    RadarEntry,
    RadarFeeds,
    RadarOptions,
)

STRONG_VERDICTS = ("proven", "strong")
SIGNIFICANT_VERDICTS = ("proven", "strong", "likely")


def _opposite_map(cands: Sequence[RadarCandidate]) -> dict[str, list[str]]:
    """Candidate key -> keys of significant candidates of the opposite sign in its group."""
    groups: dict[tuple[str, str, str], list[RadarCandidate]] = defaultdict(list)
    for c in cands:
        if c.region_group is not None and c.sig_variable and c.slope_per_decade:
            groups[(c.variable_id, c.season, c.region_group)].append(c)
    out: dict[str, list[str]] = {}
    for members in groups.values():
        for c in members:
            assert c.slope_per_decade is not None
            opp = [
                o.key
                for o in members
                if o.slope_per_decade is not None and o.slope_per_decade * c.slope_per_decade < 0
            ]
            if opp:
                out[c.key] = sorted(opp)
    return out


def _stable(e: RadarEntry, opts: RadarOptions) -> float | None:
    """Half-width ratio for the ``stable`` feed, or None if the entry does not qualify."""
    if e.verdict != "no_evidence" or e.primary_ci95 is None or not e.sigma_anom:
        return None
    lo, hi = e.primary_ci95
    if not lo <= 0.0 <= hi:
        return None
    ratio = max(abs(lo), abs(hi)) / e.sigma_anom
    return ratio if ratio <= opts.stable_halfwidth_snr else None


def _ai_flagged(e: RadarEntry, opts: RadarOptions) -> bool:
    op = e.ai_opinion
    if op is None:
        return False
    significant = e.items.get("statistics") == "pass" or e.candidate.sig_variable
    step = sum(op.class_probs.get(c, 0.0) for c in ("step", "trend_plus_step"))
    return significant and (op.predicted_class == "step" or step >= opts.ai_step_prob)


def build_feeds(
    entries: Sequence[RadarEntry],
    candidates: Sequence[RadarCandidate],
    options: RadarOptions | None = None,
) -> RadarFeeds:
    """Fills ``entry.feeds`` / ``entry.opposite_of`` in place and returns the feed lists."""
    opts = options or RadarOptions()
    opposite = _opposite_map(candidates)
    lists: dict[str, list[str]] = {f: [] for f in FEED_NAMES}
    stable: list[tuple[float, str]] = []
    breaks: list[tuple[str, str]] = []
    for e in entries:
        e.feeds = []
        e.opposite_of = opposite.get(e.key, [])
        if e.verdict in STRONG_VERDICTS:
            lists["strongest"].append(e.key)
        if e.split_flag or (e.opposite_of and e.verdict in SIGNIFICANT_VERDICTS):
            lists["opposite"].append(e.key)
        if e.shape == "accelerating" and e.items.get("statistics") == "pass":
            lists["accelerating"].append(e.key)
        if e.recent_breakpoint is not None:
            breaks.append((e.recent_breakpoint.at.isoformat(), e.key))
        if (
            e.verdict == "suspicious"
            and e.years_to_detect_remaining is not None
            and e.years_to_detect_remaining <= opts.almost_years
        ):
            lists["almost"].append(e.key)
        ratio = _stable(e, opts)
        if ratio is not None:
            stable.append((ratio, e.key))
        if _ai_flagged(e, opts):
            lists["ai_flagged"].append(e.key)
    lists["breakpoints"] = [k for _, k in sorted(breaks, key=lambda x: (x[0], x[1]), reverse=True)]
    lists["stable"] = [k for _, k in sorted(stable)]
    if opts.feed_limit is not None:
        lists = {f: v[: opts.feed_limit] for f, v in lists.items()}
    by_key = {e.key: e for e in entries}
    for f in FEED_NAMES:
        for key in lists[f]:
            by_key[key].feeds.append(f)
    return RadarFeeds.model_validate(lists)


__all__ = ["build_feeds"]
