"""Loading and validating the process graph (docs/PLAN_ANALYTICS.md section 10.1)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from earthtrend.analytics.story.models import ProcessGraph

# src/earthtrend/analytics/story/process_graph.py -> repository root
DEFAULT_PATH = Path(__file__).resolve().parents[4] / "catalog" / "processes.yaml"


def load_process_graph(path: str | Path | None = None) -> ProcessGraph:
    """Read and validate ``processes.yaml``; raises ``ValueError`` on an invalid graph."""
    p = Path(path) if path is not None else DEFAULT_PATH
    with p.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{p}: expected a mapping at the top level")
    return ProcessGraph.model_validate(data)


@lru_cache(maxsize=1)
def default_process_graph() -> ProcessGraph:
    """The catalog graph, loaded once per process."""
    return load_process_graph()


__all__ = ["DEFAULT_PATH", "default_process_graph", "load_process_graph"]
