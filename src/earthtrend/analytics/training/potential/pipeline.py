"""M2 pipeline: build-dataset -> train (+ evaluate, gates) -> promote (section 11.6).

Inputs of ``build-dataset`` (a directory):

* ``labels.csv`` - ``region_id,variable_id,season,significant,sign,snr`` (see
  ``write_labels_csv`` / ``labels_from_candidates`` for Radar stage 1 output);
* ``regions.jsonl`` - one ``RegionFeatures`` per line;
* ``variables.jsonl`` - one ``VariableInfo`` per line.

Artifacts of a version: the boosters and ``calibration.json`` (``PotentialModel.save``),
``config.yaml``, ``data_manifest.json``, ``metrics.json``, ``gates.json``, ``model_card.md``,
and a line in ``models/potential/experiments.jsonl``. ``promote`` writes ``ACTIVE`` only for
a version whose gates passed.
"""

from __future__ import annotations

import csv
import json
import platform
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from earthtrend.analytics import config
from earthtrend.analytics.ml.potential import MODEL_NAME, clear_cache, models_root
from earthtrend.analytics.ml.potential_models import RegionFeatures, VariableInfo
from earthtrend.analytics.training.potential.data import (
    PotentialDataset,
    PotentialLabel,
    build_dataset,
    synthetic_world,
)
from earthtrend.analytics.training.potential.evaluate import evaluate, gates
from earthtrend.analytics.training.potential.model import TrainConfig, train_model


def write_labels_csv(labels: Iterable[PotentialLabel], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["region_id", "variable_id", "season", "significant", "sign", "snr"])
        for lb in labels:
            w.writerow(
                [lb.region_id, lb.variable_id, lb.season, int(lb.significant), lb.sign, lb.snr]
            )


def read_inputs(
    directory: Path,
) -> tuple[list[PotentialLabel], dict[str, RegionFeatures], dict[str, VariableInfo]]:
    labels: list[PotentialLabel] = []
    with (directory / "labels.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            labels.append(
                PotentialLabel(
                    region_id=row["region_id"],
                    variable_id=row["variable_id"],
                    season=row["season"],
                    significant=row["significant"] in ("1", "true", "True"),
                    sign=int(row["sign"]),
                    snr=float(row["snr"]),
                )
            )

    def jsonl(name: str) -> list[dict[str, Any]]:
        text = (directory / name).read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    regions = {
        r.region_id: r for r in (RegionFeatures.model_validate(d) for d in jsonl("regions.jsonl"))
    }
    variables = {
        v.variable_id: v for v in (VariableInfo.model_validate(d) for d in jsonl("variables.jsonl"))
    }
    return labels, regions, variables


def write_inputs(
    directory: Path,
    labels: list[PotentialLabel],
    regions: dict[str, RegionFeatures],
    variables: dict[str, VariableInfo],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    write_labels_csv(labels, directory / "labels.csv")
    (directory / "regions.jsonl").write_text(
        "\n".join(r.model_dump_json() for r in regions.values()) + "\n", encoding="utf-8"
    )
    (directory / "variables.jsonl").write_text(
        "\n".join(v.model_dump_json() for v in variables.values()) + "\n", encoding="utf-8"
    )


def _model_card(version: str, ds: PotentialDataset, g: dict[str, Any], source: str) -> str:
    v = g["values"]
    synthetic = source == "synthetic"
    return f"""# M2 TrendPotential "Informant" - {version}

**Purpose.** For a region, rank variables and seasons by the chance that a full analysis
finds a significant trend; give the expected sign and |SNR| range (section 11.3).

**Data.** {len(ds)} rows (region x variable x season), source: `{source}`.
{"**Synthetic world - not a model of the real Earth. Never promote.**" if synthetic else ""}
Labels are Radar stage 1 (Sen + MK-AR1, BH q < 0.05); features are region and variable
descriptors only (no trends of the target: checked by `assert_no_leak`).

**Gates ({g["status"]}).** held-out spatial blocks:
recall@5 M2 {v["recall_at_5"]["m2"]:.3f} vs frequency {v["recall_at_5"]["frequency"]:.3f}
vs kNN {v["recall_at_5"]["knn"]:.3f}; Brier {v["brier"]["m2"]:.4f} vs {v["brier"]["frequency"]:.4f}
vs {v["brier"]["knn"]:.4f}; ECE {v["ece"]:.4f} (< {0.05}).

**Limits.**
- An association model: "in similar regions trends are found more often", never a cause.
- A hint, not evidence: every hint is confirmed or refuted by the real analysis, and the UI
  shows which.
- Weak supervision: labels inherit Radar stage-1 errors (about 5% false alarms per test).
- Regions unlike any in training (custom polygons over rare terrain) get less reliable hints.
"""


def train_version(
    ds: PotentialDataset,
    version: str,
    cfg: TrainConfig | None = None,
    root: Path | None = None,
    source: str = "radar",
    n_folds: int = 5,
) -> dict[str, Any]:
    """Evaluate (CV + gates), fit on all data, write every artifact. Returns the gates."""
    cfg = cfg or TrainConfig()
    out = (root or models_root()) / MODEL_NAME / version
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"version {version} already exists: {out}")
    result = evaluate(ds, cfg, n_folds=n_folds)
    g = gates(result)
    if source == "synthetic":
        g["status"] = "fail"
        g["criteria"]["real_labels"] = False
    model = train_model(ds, cfg, version)
    model.save(out)
    (out / "config.yaml").write_text(
        yaml.safe_dump(
            {"model": MODEL_NAME, "version": version, "train": cfg.as_dict(), "n_folds": n_folds}
        ),
        encoding="utf-8",
    )
    manifest = {
        "dataset_hash": ds.content_hash(),
        "source": source,
        "n_rows": len(ds),
        "n_regions": len(set(ds.region_ids)),
        "n_variables": len(set(ds.variable_ids)),
        "positive_rate": float(ds.significant.mean()),
        "split": "spatial blocks 30x60 deg (CV); variable groups (cold start)",
        "label_rule": "Radar stage 1: BH q_variable < 0.05; sign of Sen slope; |SNR|",
        "dataset_meta": ds.meta,
        "analytics_version": config.ANALYTICS_VERSION,
        "python": platform.python_version(),
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (out / "data_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out / "gates.json").write_text(json.dumps(g, indent=2), encoding="utf-8")
    (out / "model_card.md").write_text(_model_card(version, ds, g, source), encoding="utf-8")
    with (out.parent / "experiments.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"version": version, "status": g["status"], **manifest}) + "\n")
    return g


def promote(version: str, root: Path | None = None) -> None:
    base = (root or models_root()) / MODEL_NAME
    g = json.loads((base / version / "gates.json").read_text(encoding="utf-8"))
    if g.get("status") != "pass":
        raise PermissionError(f"version {version} did not pass its gates ({g.get('criteria')})")
    (base / "ACTIVE").write_text(version + "\n", encoding="utf-8")
    clear_cache()


def synthetic_inputs(directory: Path, n_regions: int = 400, seed: int = 0) -> None:
    write_inputs(directory, *synthetic_world(n_regions, seed))


def load_dataset(directory: Path) -> PotentialDataset:
    return build_dataset(*read_inputs(directory))
