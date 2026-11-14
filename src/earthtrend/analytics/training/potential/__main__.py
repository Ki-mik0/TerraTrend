"""CLI: ``python -m earthtrend.analytics.training.potential <command>``.

build-dataset --synthetic DIR         write a synthetic world (smoke runs only)
train DIR --version V [--source S]    evaluate + gates + fit + artifacts
promote V                             make V active (only if its gates passed)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from earthtrend.analytics.training.potential.model import TrainConfig
from earthtrend.analytics.training.potential.pipeline import (
    load_dataset,
    promote,
    synthetic_inputs,
    train_version,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="earthtrend-potential")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-dataset")
    b.add_argument("out", type=Path)
    b.add_argument("--synthetic", action="store_true", required=True)
    b.add_argument("--regions", type=int, default=400)
    b.add_argument("--seed", type=int, default=0)
    t = sub.add_parser("train")
    t.add_argument("data", type=Path)
    t.add_argument("--version", required=True)
    t.add_argument("--source", default="radar")
    t.add_argument("--models-dir", type=Path, default=None)
    t.add_argument("--seed", type=int, default=42)
    p = sub.add_parser("promote")
    p.add_argument("version")
    p.add_argument("--models-dir", type=Path, default=None)
    a = ap.parse_args(argv)

    if a.cmd == "build-dataset":
        synthetic_inputs(a.out, a.regions, a.seed)
        print(f"synthetic inputs written to {a.out}")
    elif a.cmd == "train":
        g = train_version(
            load_dataset(a.data), a.version, TrainConfig(seed=a.seed), a.models_dir, a.source
        )
        print(json.dumps(g, indent=2))
    else:
        promote(a.version, a.models_dir)
        print(f"{a.version} is active")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
