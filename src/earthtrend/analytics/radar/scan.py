"""Two-stage scan of the Radar of trends (docs/PLAN_ANALYTICS.md section 9.2, stage A8).

Stage 1 (cheap, every (variable, region, season) series):
* the same preparation as the series core (log transform, period, monthly climatology over
  the baseline, anomalies; seasons: 3-month means, anomalies against the seasonal mean),
  vectorized over series that share a time axis;
* annual means of anomalies with the validity rules of section 4.1 (as the grid, 8.1);
* MK-AR1 + Sen + Gilbert CI on the annual (seasonal) means in a numba kernel;
* SNR = |Sen slope per decade| / sigma of the anomalies (monthly anomalies for ``annual``,
  as ``analyze_series``);
* Benjamini-Hochberg on p_MK within each variable and over the whole scan;
* M1 opinions, when a model is passed (optional; without it ``ai_*`` stay empty).

Stage 2 (top N by priority): ``analyze_series`` + ``build_protocol`` for each candidate.
"""

from __future__ import annotations

import time
import warnings
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy import stats

from earthtrend.analytics import config
from earthtrend.analytics.analyze import analyze_series, to_monthly
from earthtrend.analytics.evidence.protocol import build_protocol
from earthtrend.analytics.models import (
    AiOpinion,
    AnalysisOptions,
    ClimateIndex,
    RegionalSeries,
    Season,
)
from earthtrend.analytics.preprocess.aggregate import FloatArray, split_dates
from earthtrend.analytics.radar import _kernels as k
from earthtrend.analytics.radar.feeds import build_feeds
from earthtrend.analytics.radar.models import (
    AiDetective,
    RadarCandidate,
    RadarEntry,
    RadarOptions,
    RadarRun,
    RadarSeries,
    radar_key,
)
from earthtrend.analytics.radar.scoring import apply_novelty, score_entries
from earthtrend.analytics.radar.typology import typology_from_candidates
from earthtrend.analytics.spatial.fdr import benjamini_hochberg
from earthtrend.analytics.trend.mann_kendall import TIE_RESOLUTION

STEP_CLASSES = ("step", "trend_plus_step")
TREND_CLASSES = ("linear", "accelerating", "trend_plus_step")


@dataclass(frozen=True)
class YearlyBlock:
    """Annual (seasonal) means of anomalies for a group of series sharing one time axis."""

    rows: list[int]  # indices into the scan inputs
    years: np.ndarray  # (n_years,) int
    values: FloatArray  # (rows, n_years)
    sigma: FloatArray  # (rows,) sigma of the anomalies used for SNR


def _nanmean(x: FloatArray, axis: int) -> FloatArray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.asarray(np.nanmean(x, axis=axis))


def _nanstd(x: FloatArray, axis: int) -> FloatArray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        n = np.sum(np.isfinite(x), axis=axis)
        sd = np.asarray(np.nanstd(x, axis=axis, ddof=1))
        return np.where(n > 1, sd, np.nan)


@dataclass(frozen=True)
class SeriesMatrix:
    """Values (analysis units, log applied) of series sharing one monthly time axis."""

    years: np.ndarray
    months: np.ndarray
    values: FloatArray  # (rows, time)


def series_matrix(series: Sequence[RegionalSeries], rows: list[int]) -> SeriesMatrix:
    """Stack series sharing one monthly calendar into a (series, months) matrix in analysis
    units (log transform applied where the passport asks for it).
    """
    years, months = split_dates(series[rows[0]].dates)
    raw = np.array(
        [[np.nan if v is None else v for v in series[r].values] for r in rows], dtype=np.float64
    ).reshape(len(rows), years.size)
    logs = np.array([series[r].meta.transform == "log" for r in rows])
    if logs.any():
        with np.errstate(divide="ignore", invalid="ignore"):
            raw[logs] = np.where(raw[logs] > 0, np.log(raw[logs]), np.nan)
    return SeriesMatrix(years, months, raw)


def yearly_block(
    series: Sequence[RegionalSeries],
    rows: list[int],
    season: Season,
    period: tuple[int, int] | None = None,
    baseline: tuple[int, int] | None = None,
) -> YearlyBlock:
    """Vectorized ``prepare_series`` + annual means for series with identical monthly dates."""
    return yearly_block_from(series_matrix(series, rows), rows, season, period, baseline)


def yearly_block_from(
    mat: SeriesMatrix,
    rows: list[int],
    season: Season,
    period: tuple[int, int] | None = None,
    baseline: tuple[int, int] | None = None,
) -> YearlyBlock:
    """Annual (or seasonal) anomaly block (series, years) for Radar stage 1, with the same
    period, DJF and baseline rules as ``prepare_series``.
    """
    years, months, vals = mat.years, mat.months, mat.values
    if period is not None:
        sel = (years >= period[0]) & (years <= period[1])
        if season == "DJF":
            sel |= (years == period[0] - 1) & (months == 12)
        years, months, vals = years[sel], months[sel], vals[:, sel]
    nr = len(rows)
    if years.size == 0:
        return YearlyBlock(rows, np.empty(0, np.int64), np.empty((nr, 0)), np.full(nr, np.nan))

    y0 = int(years.min())
    ny = int(years.max()) - y0 + 1
    cube = np.full((nr, ny, 12), np.nan)
    cube[:, years - y0, months - 1] = vals
    present = np.zeros(ny, dtype=bool)  # calendar years that appear in the record
    present[years - y0] = True
    all_years = np.arange(y0, y0 + ny, dtype=np.int64)

    if season == "annual":
        in_base = (
            (all_years >= baseline[0]) & (all_years <= baseline[1])
            if baseline
            else np.ones(ny, dtype=bool)
        )
        clim = _nanmean(cube[:, in_base, :], axis=1)  # (rows, 12)
        anom = cube - clim[:, None, :]
        sigma = _nanstd(anom.reshape(nr, -1), axis=1)
        ok = np.isfinite(anom)
        count = ok.sum(axis=2)
        valid = count >= config.ANNUAL_MIN_MONTHS
        for ms in config.SEASON_MONTHS.values():
            missing = 3 - ok[:, :, [m - 1 for m in ms]].sum(axis=2)
            valid &= missing < 2
        with np.errstate(divide="ignore", invalid="ignore"):
            ann = np.where(valid, np.nansum(np.where(ok, anom, 0.0), axis=2) / count, np.nan)
        ann = ann[:, present]
        return YearlyBlock(rows, all_years[present], ann, sigma)

    ms = config.SEASON_MONTHS[season]
    sv = np.full((nr, ny), np.nan)
    emit = np.zeros(ny, dtype=bool)
    for i in range(ny):
        if season == "DJF":
            if i == 0 or not (present[i - 1] and present[i]):
                continue
            parts = [cube[:, i - 1, 11], cube[:, i, 0], cube[:, i, 1]]
        else:
            if not present[i]:
                continue
            parts = [cube[:, i, m - 1] for m in ms]
        emit[i] = True
        sv[:, i] = (parts[0] + parts[1] + parts[2]) / 3.0  # NaN unless all 3 months exist
    sy = all_years[emit]
    sv = sv[:, emit]
    if period is not None:
        keep = (sy >= period[0]) & (sy <= period[1])
        sy, sv = sy[keep], sv[:, keep]
    in_base = (sy >= baseline[0]) & (sy <= baseline[1]) if baseline else np.ones(sy.size, bool)
    mu = _nanmean(sv[:, in_base], axis=1)
    anom = sv - mu[:, None]
    return YearlyBlock(rows, sy, anom, _nanstd(anom, axis=1))


def _ai_step_prob(op: AiOpinion) -> float:
    return float(sum(op.class_probs.get(c, 0.0) for c in STEP_CLASSES))


def ai_disagrees(significant: bool, sign: int, op: AiOpinion | None) -> bool:
    """Statistics vs M1 (section 9.2): significant but AI sees no trend or a step, or not
    significant while AI is confident about a trend, or opposite slope signs."""
    if op is None:
        return False
    cls = op.predicted_class
    if significant:
        if cls in ("no_trend", "step"):
            return True
        return bool(sign and op.slope_per_decade and np.sign(op.slope_per_decade) != sign)
    return cls in TREND_CLASSES and op.confidence == "high"


def _priority(c: RadarCandidate, opts: RadarOptions) -> float:
    if c.q_variable is None or c.snr is None or not np.isfinite(c.snr):
        return -np.inf
    p = (1.0 - c.q_variable) * min(c.snr / config.SNR_STRONG, 2.0)
    return p + (opts.ai_disagree_bonus if c.ai_disagrees else 0.0)


def _months_between(a: date, b: date) -> int:
    return abs((a.year - b.year) * 12 + a.month - b.month)


def scan_stage1(
    inputs: Sequence[RadarSeries],
    options: RadarOptions | None = None,
    ai: AiDetective | None = None,
) -> tuple[list[RadarCandidate], dict[str, AiOpinion], list[str]]:
    """Stage 1 over every input x season.

    Returns (candidates in season x input order, M1 opinions by key, warning codes).
    Numbers are collected in arrays; candidates are built once at the end.
    """
    opts = options or RadarOptions()
    series = [to_monthly(i.series) for i in inputs]
    ns = len(series)
    z_crit = float(stats.norm.ppf(1 - opts.alpha / 2))
    groups: dict[tuple[date, ...], list[int]] = defaultdict(list)
    for r, s in enumerate(series):
        groups[tuple(s.dates)].append(r)
    matrices = {gk: series_matrix(series, rows) for gk, rows in groups.items()}

    n_seasons = len(opts.seasons)
    res = np.full((n_seasons, ns, k.N_OUT), np.nan)
    sigma = np.full((n_seasons, ns), np.nan)
    first = np.full((n_seasons, ns), -1, dtype=np.int64)
    last = np.full((n_seasons, ns), -1, dtype=np.int64)
    ops: list[list[AiOpinion | None]] = []
    warn: list[str] = []
    for si, season in enumerate(opts.seasons):
        season_ops: list[AiOpinion | None] = [None] * ns
        if ai is not None and series:
            ai_opts = AnalysisOptions(season=season, period=opts.period, baseline=opts.baseline)
            try:
                got = list(ai(series, ai_opts))
            except Exception:  # advisory component: the scan never fails because of M1
                got = []
                warn.append("ai_failed")
            if len(got) == ns:
                season_ops = got
            elif got:
                warn.append("ai_wrong_length")
        ops.append(season_ops)

        for gk, rows in groups.items():
            blk = yearly_block_from(matrices[gk], rows, season, opts.period, opts.baseline)
            if not blk.years.size:
                continue
            out = k.yearly_trends(
                np.ascontiguousarray(blk.values),
                blk.years.astype(np.float64),
                z_crit,
                TIE_RESOLUTION,
            )
            res[si, rows] = out
            sigma[si, rows] = blk.sigma
            fin = np.isfinite(blk.values)
            has = fin.any(axis=1)
            fi = np.argmax(fin, axis=1)
            li = blk.years.size - 1 - np.argmax(fin[:, ::-1], axis=1)
            first[si, rows] = np.where(has, blk.years[fi], -1)
            last[si, rows] = np.where(has, blk.years[li], -1)

    # Flatten to season x input order.
    res2 = res.reshape(-1, k.N_OUT)
    sig2 = sigma.ravel()
    sen, z = res2[:, k.SEN], res2[:, k.Z_MK]
    n_years = np.nan_to_num(res2[:, k.N], nan=0.0).astype(np.int64)
    min_years = np.tile(
        np.array([opts.min_years or s.meta.min_years_for_trend for s in series], dtype=np.int64),
        n_seasons,
    )
    short = n_years < min_years
    tested = ~short & np.isfinite(sen) & np.isfinite(z)
    with np.errstate(invalid="ignore", divide="ignore"):
        p_mk = np.where(tested, 2 * stats.norm.sf(np.abs(z)), np.nan)
        spd = sen * 10
        snr = np.where(sig2 > 0, np.abs(spd) / sig2, 0.0)

    var_ids = [s.meta.variable_id for s in series] * n_seasons
    sig_g, q_g, _ = benjamini_hochberg(p_mk, opts.fdr_alpha)
    sig_v = np.zeros(p_mk.size, dtype=bool)
    q_v = np.full(p_mk.size, np.nan)
    by_var: dict[str, list[int]] = defaultdict(list)
    for i, v in enumerate(var_ids):
        by_var[v].append(i)
    for idx in by_var.values():
        s_, q_, _ = benjamini_hochberg(p_mk[idx], opts.fdr_alpha)
        sig_v[idx], q_v[idx] = s_, q_

    cands: list[RadarCandidate] = []
    opinions: dict[str, AiOpinion] = {}
    for si, season in enumerate(opts.seasons):
        for r, s in enumerate(series):
            i = si * ns + r
            meta = s.meta
            key = radar_key(meta.variable_id, meta.region_id, season)
            op = ops[si][r]
            if op is not None:
                opinions[key] = op
            d: dict[str, object] = {
                "key": key,
                "variable_id": meta.variable_id,
                "concept_id": meta.concept_id,
                "dataset_id": meta.dataset_id,
                "region_id": meta.region_id,
                "region_group": inputs[r].region_group,
                "season": season,
                "region_area_km2": meta.region_area_km2,
                "n_years": int(n_years[i]),
                "first_year": int(first[si, r]) if first[si, r] >= 0 else None,
                "last_year": int(last[si, r]) if last[si, r] >= 0 else None,
                "ai_class": op.predicted_class if op else None,
                "ai_step_prob": _ai_step_prob(op) if op else None,
                "ai_confidence": op.confidence if op else None,
            }
            if tested[i]:
                sign = int(np.sign(spd[i]))
                d.update(
                    slope_per_decade=float(spd[i]),
                    ci95=(float(res2[i, k.CI_LO] * 10), float(res2[i, k.CI_HI] * 10)),
                    p_mk=float(p_mk[i]),
                    z_mk=float(z[i]),
                    sigma_anom=float(sig2[i]),
                    snr=float(snr[i]),
                    signed_snr=float(sign * snr[i]),
                    q_variable=float(q_v[i]),
                    q_global=float(q_g[i]),
                    sig_variable=bool(sig_v[i]),
                    sig_global=bool(sig_g[i]),
                    ai_disagrees=ai_disagrees(bool(sig_v[i]), sign, op),
                )
            else:
                d.update(skipped="short_record" if short[i] else "no_test", priority=-np.inf)
            c = RadarCandidate.model_validate(d)
            if tested[i]:
                c.priority = _priority(c, opts)
            cands.append(c)
    return cands, opinions, warn


def select_top(cands: Sequence[RadarCandidate], top_n: int) -> list[RadarCandidate]:
    """Stage 2 queue: tested candidates by priority (ties broken by key, deterministic)."""
    tested = [c for c in cands if c.skipped is None]
    return sorted(tested, key=lambda c: (-c.priority, c.key))[:top_n]


def _recent_breakpoint(
    entry: RadarEntry, period_end: date | None, inp: RadarSeries, opts: RadarOptions
) -> None:
    """Most probable change point > breakpoint_prob within the last years, no sensor event."""
    if period_end is None:
        return
    horizon = opts.breakpoint_recent_years * 12
    best = None
    for cp in entry.changepoints:
        if cp.probability is None or cp.probability <= opts.breakpoint_prob:
            continue
        if cp.at > period_end or _months_between(cp.at, period_end) > horizon:
            continue
        if any(
            _months_between(cp.at, ev.date) <= opts.sensor_window_months for ev in inp.sensor_events
        ):
            continue
        if best is None or cp.probability > (best.probability or 0.0):
            best = cp
    entry.recent_breakpoint = best
    entry.new_breakpoint = best is not None


def scan_stage2(
    inputs: Sequence[RadarSeries],
    selected: Sequence[RadarCandidate],
    opinions: dict[str, AiOpinion],
    options: RadarOptions | None = None,
    indices: list[ClimateIndex] | None = None,
) -> list[RadarEntry]:
    """Full protocol (``analyze_series`` + ``build_protocol``) for each selected candidate."""
    opts = options or RadarOptions()
    row_of = {(i.series.meta.variable_id, i.series.meta.region_id): r for r, i in enumerate(inputs)}
    entries: list[RadarEntry] = []
    for c in selected:
        inp = inputs[row_of[(c.variable_id, c.region_id)]]
        a_opts = AnalysisOptions(
            period=opts.period,
            season=c.season,
            baseline=opts.baseline,
            alpha=opts.alpha,
            changepoints=opts.changepoints,
            seasonal_breakdown=False,
            seed=opts.seed,
        )
        tr = analyze_series(inp.series, a_opts)
        split = inp.splits.get(c.season)
        prot = build_protocol(
            inp.series,
            a_opts.model_copy(update={"changepoints": False}),
            witnesses=inp.witnesses,
            indices=indices,
            changepoints=[cp.at for cp in tr.changepoints] if opts.changepoints else None,
            sensor_events=inp.sensor_events,
            split=split,
        )
        mag = tr.magnitude
        entry = RadarEntry(
            key=c.key,
            candidate=c,
            verdict=prot.verdict,
            strength=prot.strength,
            direction=prot.direction,
            caveats=prot.caveats,
            items={i.key: i.status for i in prot.items},
            primary_slope_per_decade=tr.primary_slope_per_decade,
            primary_ci95=tr.primary_ci95,
            sigma_anom=mag.sigma_anom if mag else None,
            snr=mag.snr if mag else None,
            years_to_detect=tr.years_to_detect,
            years_to_detect_remaining=tr.years_to_detect_remaining,
            shape=tr.nonlinear.shape if tr.nonlinear else None,
            changepoints=tr.changepoints,
            split_flag=bool(split and split.split_flag),
            ai_opinion=opinions.get(c.key) or tr.ai_opinion,
        )
        _recent_breakpoint(entry, tr.period_used[1] if tr.period_used else None, inp, opts)
        entries.append(entry)
    return entries


def run_radar(
    inputs: Sequence[RadarSeries | RegionalSeries],
    options: RadarOptions | None = None,
    *,
    indices: list[ClimateIndex] | None = None,
    previous: RadarRun | Sequence[RadarEntry] | None = None,
    ai: AiDetective | None = None,
) -> RadarRun:
    """Stage 1 on everything, stage 2 on the top N, novelty, score, feeds, typology."""
    opts = options or RadarOptions()
    items = [i if isinstance(i, RadarSeries) else RadarSeries(series=i) for i in inputs]
    seen: set[tuple[str, str]] = set()
    for i in items:
        pair = (i.series.meta.variable_id, i.series.meta.region_id)
        if pair in seen:
            raise ValueError(f"duplicate (variable_id, region_id) in radar inputs: {pair}")
        seen.add(pair)

    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    cands, opinions, warn = scan_stage1(items, opts, ai)
    timings["stage1"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    entries = scan_stage2(items, select_top(cands, opts.top_n), opinions, opts, indices)
    timings["stage2"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    prev = previous.entries if isinstance(previous, RadarRun) else previous
    dropped = apply_novelty(entries, prev, opts)
    score_entries(entries, opts)
    entries.sort(key=lambda e: (-e.radar_score, e.key))
    feeds = build_feeds(entries, cands, opts)
    typ = (
        typology_from_candidates(cands, season="annual", seed=opts.seed) if opts.typology else None
    )
    timings["post"] = time.perf_counter() - t0

    return RadarRun(
        options=opts,
        n_series=len(items),
        n_tested=sum(c.skipped is None for c in cands),
        n_sig_variable=sum(c.sig_variable for c in cands),
        n_sig_global=sum(c.sig_global for c in cands),
        candidates=cands,
        entries=entries,
        feeds=feeds,
        dropped=dropped,
        typology=typ,
        ai_model_version=next(iter(opinions.values())).model_version if opinions else None,
        warnings=warn,
        timings_s=timings,
    )


__all__ = [
    "ai_disagrees",
    "run_radar",
    "scan_stage1",
    "scan_stage2",
    "select_top",
    "yearly_block",
]
