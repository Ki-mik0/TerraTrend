"""M3 VarSearch inference: find variables by a human query in UA or EN (PLAN_ANALYTICS 11.4).

Mirrors `GET /api/v1/variables?q=` (Plan_Backend, `ListVariables`): a query plus the
catalog filters `theme`, `domain`, `seasonal`, a page and a page size. Filters the analytics
package cannot know (e.g. `has_precomputed`) are applied by the backend through `allowed_ids`.

Modes:
* `hybrid` - the active fine-tuned model fused with BM25 (score = a * dense + (1 - a) * bm25,
  each min-max scaled over the catalog);
* `bm25` - lexical only. Used when there is no active model, the model's quality gate is not
  `pass`, or `sentence-transformers` is not installed. The app works fully without models.
* `catalog` - empty query: catalog order.

Model versions live in `models/varsearch/{version}/` (11.6) and the active one is named in
`models/varsearch/ACTIVE`, written only by `promote` after the gate passed.
"""

from __future__ import annotations

import functools
import json
import os
from collections.abc import Collection
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict

from earthtrend.analytics.ml.varsearch_catalog import (
    VariableCatalog,
    load_catalog,
    passage_text,
)
from earthtrend.analytics.ml.varsearch_encoders import (
    Encoder,
    HashingEncoder,
    SentenceTransformerEncoder,
)
from earthtrend.analytics.ml.varsearch_lexical import LexicalSearcher

MODEL_NAME = "varsearch"
ACTIVE_FILE = "ACTIVE"
DEFAULT_ALPHA = 0.7
# Lexical scores: best stem match = 1, best trigram match = 0.5 (see varsearch_lexical).
BM25_MIN_SCORE = 0.15
Mode = Literal["hybrid", "dense", "bm25"]
Method = Literal["hybrid", "dense", "bm25", "catalog"]


class VariableHit(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    rank: int
    score: float


class VariableSearchPage(BaseModel):
    model_config = ConfigDict(frozen=True)
    query: str
    items: list[VariableHit]
    total: int
    page: int
    page_size: int
    method: Method
    model_version: str | None = None
    fallback_reason: str | None = None


def _minmax(x: np.ndarray) -> np.ndarray:
    if x.size == 0:
        return x
    lo, hi = float(x.min()), float(x.max())
    return (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)


def fuse(dense: np.ndarray, lexical: np.ndarray, alpha: float = DEFAULT_ALPHA) -> np.ndarray:
    """Convex combination of min-max scaled dense and lexical scores."""
    return alpha * _minmax(dense) + (1.0 - alpha) * _minmax(lexical)


class Retriever:
    """Scores every catalog variable for a query. Shared by inference and evaluation."""

    def __init__(
        self,
        catalog: VariableCatalog,
        encoder: Encoder | None = None,
        *,
        mode: Mode = "hybrid",
        alpha: float = DEFAULT_ALPHA,
    ) -> None:
        if mode != "bm25" and encoder is None:
            raise ValueError(f"mode {mode!r} needs an encoder")
        self.catalog = catalog
        self.ids = catalog.ids
        self.mode: Mode = mode
        self.alpha = alpha
        self.encoder = encoder
        self.lexical = LexicalSearcher(catalog)
        self._doc_emb: np.ndarray | None = None
        if encoder is not None and mode != "bm25":
            self._doc_emb = encoder.encode([passage_text(d) for d in catalog.variables], "passage")

    def scores_many(self, queries: list[str]) -> np.ndarray:
        """(n_queries, n_variables) scores; dense queries are encoded in one batch."""
        lex = np.stack([self.lexical.scores(q) for q in queries]) if queries else np.zeros((0,))
        if self.mode == "bm25":
            return lex
        assert self.encoder is not None and self._doc_emb is not None
        dense = self.encoder.encode(queries, "query") @ self._doc_emb.T
        if self.mode == "dense":
            return dense.astype(np.float64)
        return np.stack([fuse(d, lx, self.alpha) for d, lx in zip(dense, lex, strict=True)])

    def scores(self, query: str) -> np.ndarray:
        return self.scores_many([query])[0]

    def rank_many(self, queries: list[str]) -> list[list[str]]:
        s = self.scores_many(queries)
        # Stable sort keeps catalog order among ties.
        return [[self.ids[j] for j in np.argsort(-row, kind="stable")] for row in s]


# ---------------------------------------------------------------- model directory


def models_root(models_dir: str | Path | None = None) -> Path:
    if models_dir is not None:
        return Path(models_dir)
    env = os.environ.get("MODELS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "models"


def active_version(models_dir: str | Path | None = None) -> str | None:
    p = models_root(models_dir) / MODEL_NAME / ACTIVE_FILE
    if not p.is_file():
        return None
    v = p.read_text(encoding="utf-8").strip()
    return v or None


def read_gates(version_dir: Path) -> dict[str, Any] | None:
    p = version_dir / "gates.json"
    if not p.is_file():
        return None
    data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return data


def load_encoder(version_dir: Path, config: dict[str, Any]) -> Encoder:
    enc = config.get("encoder", {})
    kind = enc.get("kind")
    if kind == "hashing":
        return HashingEncoder(dim=int(enc.get("dim", 512)))
    if kind == "sentence-transformers":
        return SentenceTransformerEncoder(
            version_dir / enc.get("path", "model"),
            query_prefix=enc.get("query_prefix", "query: "),
            passage_prefix=enc.get("passage_prefix", "passage: "),
        )
    raise ValueError(f"unknown encoder kind {kind!r}")


# ---------------------------------------------------------------- public search


class VarSearch:
    """Search over a catalog; BM25 unless a gated model is supplied."""

    def __init__(
        self,
        catalog: VariableCatalog,
        encoder: Encoder | None = None,
        *,
        alpha: float = DEFAULT_ALPHA,
        model_version: str | None = None,
        fallback_reason: str | None = None,
    ) -> None:
        self.catalog = catalog
        self.model_version = model_version if encoder is not None else None
        self.fallback_reason = None if encoder is not None else (fallback_reason or "no_model")
        mode: Mode = "hybrid" if encoder is not None else "bm25"
        self.retriever = Retriever(catalog, encoder, mode=mode, alpha=alpha)

    @property
    def mode(self) -> Mode:
        return self.retriever.mode

    @classmethod
    def from_models_dir(
        cls,
        catalog: VariableCatalog,
        models_dir: str | Path | None = None,
        *,
        version: str | None = None,
        allow_ungated: bool = False,
    ) -> VarSearch:
        """Load the active (or given) version; fall back to BM25 with a reason on any problem.

        `allow_ungated=True` is for offline experiments only: the product never serves a
        model whose `gates.json` is not `pass` (PLAN_ANALYTICS 11.1, principle 2).
        """
        root = models_root(models_dir) / MODEL_NAME
        version = version or active_version(models_dir)
        if version is None:
            return cls(catalog, fallback_reason="no_active_model")
        vdir = root / version
        cfg_path = vdir / "config.yaml"
        if not cfg_path.is_file():
            return cls(catalog, fallback_reason=f"missing_config:{version}")
        gates = read_gates(vdir)
        status = (gates or {}).get("overall", "missing")
        if status != "pass" and not allow_ungated:
            return cls(catalog, fallback_reason=f"gate_{status}:{version}")
        config = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        try:
            encoder = load_encoder(vdir, config)
        except ImportError:
            return cls(catalog, fallback_reason="dependency_missing:sentence-transformers")
        except Exception as exc:  # corrupt weights etc.: never break the app
            return cls(catalog, fallback_reason=f"load_error:{type(exc).__name__}")
        alpha = float(config.get("fusion", {}).get("alpha", DEFAULT_ALPHA))
        return cls(catalog, encoder, alpha=alpha, model_version=version)

    def search(
        self,
        q: str | None,
        *,
        theme: str | None = None,
        domain: str | None = None,
        seasonal: bool | None = None,
        allowed_ids: Collection[str] | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> VariableSearchPage:
        if page < 1 or page_size < 1:
            raise ValueError("page and page_size must be >= 1")
        keep = np.array(
            [
                (theme is None or v.theme == theme)
                and (domain is None or v.domain == domain)
                and (seasonal is None or v.seasonal == seasonal)
                and (allowed_ids is None or v.id in allowed_ids)
                for v in self.catalog.variables
            ],
            dtype=bool,
        )
        query = (q or "").strip()
        method: Method
        if not query:
            method = "catalog"
            idx = np.flatnonzero(keep)
            scores = np.zeros(len(self.catalog.variables))
        else:
            method = self.mode
            scores = self.retriever.scores(query)
            if method == "bm25":
                # lexical only: drop variables that share just a few character trigrams
                keep &= scores >= BM25_MIN_SCORE
            order = np.argsort(-scores, kind="stable")
            idx = order[keep[order]]
        total = int(idx.size)
        start = (page - 1) * page_size
        items = [
            VariableHit(id=self.catalog.variables[j].id, rank=start + k + 1, score=float(scores[j]))
            for k, j in enumerate(idx[start : start + page_size])
        ]
        return VariableSearchPage(
            query=query,
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            method=method,
            model_version=self.model_version,
            fallback_reason=self.fallback_reason if method != "catalog" else None,
        )


@functools.cache
def default_searcher() -> VarSearch:
    """Starter catalog + active model from `MODELS_DIR` (or `models/`), cached per process."""
    return VarSearch.from_models_dir(load_catalog())


def search_variables(
    q: str | None,
    *,
    theme: str | None = None,
    domain: str | None = None,
    seasonal: bool | None = None,
    allowed_ids: Collection[str] | None = None,
    page: int = 1,
    page_size: int = 20,
    searcher: VarSearch | None = None,
) -> VariableSearchPage:
    """Entry point behind `GET /api/v1/variables?q=`."""
    s = searcher if searcher is not None else default_searcher()
    return s.search(
        q,
        theme=theme,
        domain=domain,
        seasonal=seasonal,
        allowed_ids=allowed_ids,
        page=page,
        page_size=page_size,
    )
