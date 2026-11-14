"""Models of Story Lens (docs/PLAN_ANALYTICS.md section 10, stage A8).

The process graph is data (``catalog/processes.yaml``) validated by ``ProcessGraph``.
``StoryFacts`` holds every number a story text may quote; texts are written elsewhere
(template, external LLM or M4) and checked against these facts.
"""

from __future__ import annotations

import re
from collections import deque
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from earthtrend.analytics import config
from earthtrend.analytics.models import AiOpinion, Direction, Season, VerdictCode

CODE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_LAG_MONTHS = 24
TrendSign = Literal["up", "down", "none"]
Consistency = Literal["consistent", "inconsistent", "unclear"]


# ---------------------------------------------------------------- process graph (10.1)


class ProcessNode(BaseModel):
    id: str
    group: str = "other"


class ProcessEdge(BaseModel):
    source: str
    target: str
    expected_sign: Literal[-1, 1]
    lag_months: int = Field(ge=0, le=MAX_LAG_MONTHS)
    mechanism_code: str


class GraphPath(BaseModel):
    """Route from the main concept to a related one."""

    concept_id: str
    depth: int
    path: list[str]  # concepts, main first
    mechanism_codes: list[str]
    expected_sign: Literal[-1, 1]  # product of edge signs
    lag_months: int  # > 0: the related concept responds after the main one; < 0: it leads


class ProcessGraph(BaseModel):
    version: str
    control_concept: str
    nodes: list[ProcessNode]
    edges: list[ProcessEdge]

    @model_validator(mode="after")
    def _check(self) -> ProcessGraph:
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate node ids: {dup}")
        for i in ids:
            if not CODE_RE.match(i):
                raise ValueError(f"node id is not snake_case: {i!r}")
        known = set(ids)
        if self.control_concept not in known:
            raise ValueError(f"control_concept {self.control_concept!r} is not a node")
        pairs: set[tuple[str, str]] = set()
        for e in self.edges:
            for end in (e.source, e.target):
                if end not in known:
                    raise ValueError(f"edge refers to unknown node {end!r}")
            if e.source == e.target:
                raise ValueError(f"self-loop on {e.source!r}")
            if (e.source, e.target) in pairs:
                raise ValueError(f"duplicate edge {e.source} -> {e.target}")
            pairs.add((e.source, e.target))
            if not CODE_RE.match(e.mechanism_code):
                raise ValueError(f"mechanism_code is not snake_case: {e.mechanism_code!r}")
        return self

    def has(self, concept_id: str) -> bool:
        return any(n.id == concept_id for n in self.nodes)

    def neighbors(self, concept_id: str, max_depth: int = 2) -> list[GraphPath]:
        """Concepts within ``max_depth`` edges (undirected BFS, shortest path, file order)."""
        if not self.has(concept_id):
            return []
        adj: dict[str, list[tuple[str, ProcessEdge, int]]] = {n.id: [] for n in self.nodes}
        for e in self.edges:
            adj[e.source].append((e.target, e, +1))  # walking with the edge: response later
            adj[e.target].append((e.source, e, -1))  # against the edge: the other one leads
        seen = {concept_id}
        out: list[GraphPath] = []
        queue: deque[tuple[str, list[str], list[str], int, int]] = deque(
            [(concept_id, [concept_id], [], 1, 0)]
        )
        while queue:
            node, path, mechs, sign, lag = queue.popleft()
            if len(path) - 1 >= max_depth:
                continue
            for nxt, e, direction in adj[node]:
                if nxt in seen:
                    continue
                seen.add(nxt)
                item = (
                    nxt,
                    [*path, nxt],
                    [*mechs, e.mechanism_code],
                    sign * e.expected_sign,
                    lag + direction * e.lag_months,
                )
                out.append(
                    GraphPath(
                        concept_id=nxt,
                        depth=len(item[1]) - 1,
                        path=item[1],
                        mechanism_codes=item[2],
                        expected_sign=1 if item[3] > 0 else -1,
                        lag_months=item[4],
                    )
                )
                queue.append(item)
        return out


# ---------------------------------------------------------------- related variables (10.2)


class RelatedVariable(BaseModel):
    variable_id: str
    concept_id: str
    dataset_id: str
    route: GraphPath
    season: Season
    slope_per_decade: float | None
    ci95: tuple[float, float] | None
    p_mk: float | None
    direction: Direction
    verdict: VerdictCode  # quick verdict of ``analyze_series`` (no witnesses / alibi)
    strength: float = Field(ge=0.0, le=1.0)  # that verdict's strength, scaled to 0..1
    lag_used_months: int  # lag applied to the correlation (in years x 12 for seasons)
    n_overlap: int
    corr: float | None  # Pearson r of detrended anomalies at the edge lag
    corr_p: float | None  # with AR(1) effective sample size (Bretherton et al. 1999)
    n_eff: float | None
    partial_corr: float | None  # controlling for the control concept (temperature)
    partial_p: float | None
    controlled_for: str | None
    corr_consistency: Consistency  # sign of r vs the expected sign of the route
    trend_consistency: Consistency  # trend directions vs the expected sign


# ---------------------------------------------------------------- patterns (10.3)


class ConceptTrend(BaseModel):
    """Trend of one concept in the story's region, the input of the pattern library."""

    concept_id: str
    season: Season = "annual"
    direction: TrendSign
    significant: bool
    strength: float = Field(ge=0.0, le=1.0)  # evidence strength (protocol strength / 100)
    variable_id: str | None = None
    slope_per_decade: float | None = None
    verdict: VerdictCode | None = None


class PatternContext(BaseModel):
    cold_region: bool = False  # e.g. boreal / high-mountain: warming may cause greening


class ConditionResult(BaseModel):
    code: str
    required: bool
    met: bool | None  # None: no data for any option
    score: float
    concept_used: str | None = None
    seen: TrendSign | None = None


class PatternMatch(BaseModel):
    code: str
    confidence: float = Field(ge=0.0, le=1.0)
    conditions: list[ConditionResult]
    n_counted: int


# ---------------------------------------------------------------- facts (10.4)


class MainTrendFacts(BaseModel):
    variable_id: str
    concept_id: str
    dataset_id: str
    region_id: str
    season: Season
    units: str
    period_start: date | None
    period_end: date | None
    years_of_data: float
    slope_per_decade: float | None
    ci95: tuple[float, float] | None
    percent_per_decade: float | None
    snr: float | None
    snr_class: str | None
    p_ols_annual: float | None
    p_ols: float | None
    p_mk: float | None
    years_to_detect: float | None
    direction: Direction
    verdict: VerdictCode
    strength: int
    ruleset: str
    shape: str | None = None


class AlibiFacts(BaseModel):
    status: str
    b_raw_per_decade: float | None = None
    b_adjusted_per_decade: float | None = None
    p_adjusted: float | None = None
    partial_r2: float | None = None
    terms: list[dict[str, Any]] = Field(default_factory=list)  # index, lag, coefficient
    rejected: list[str] = Field(default_factory=list)


class WitnessFacts(BaseModel):
    status: str
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    n_pairs_diverging: int = 0


class StoryFacts(BaseModel):
    main: MainTrendFacts
    related: list[RelatedVariable] = Field(default_factory=list)
    patterns: list[PatternMatch] = Field(default_factory=list)
    alibi: AlibiFacts | None = None
    witnesses: WitnessFacts | None = None
    ai_opinion: AiOpinion | None = None
    ai_status: str | None = None  # ai_expert item status, when present
    caveats: list[str] = Field(default_factory=list)  # mandatory caveat codes
    # Every number a text may quote, flat: "main.slope_per_decade", "related.ndvi.corr", ...
    numbers: dict[str, float] = Field(default_factory=dict)
    graph_version: str | None = None
    analytics_version: str = config.ANALYTICS_VERSION
