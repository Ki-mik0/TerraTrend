"""End-to-end M3 run: dataset -> fine-tune -> evaluate -> gate -> artifacts (PLAN_ANALYTICS 11.6).

Writes `models/varsearch/{version}/`:
  model/              fine-tuned sentence-transformers weights (sentence-transformers encoder)
  data/               pairs_train.jsonl, pairs_dev.jsonl
  config.yaml         encoder, fusion, training and generator parameters, seeds
  data_manifest.json  hashes, versions, split rule, counts
  metrics.json        every system on the synthetic dev set and (if present) the human test
  gates.json          pass / fail / not_evaluated per criterion
  model_card.md       purpose, data, metrics, limitations
and appends one line to `models/varsearch/experiments.jsonl`.

`encoder="hashing"` runs the whole pipeline without torch or downloads (smoke tests): base
and tuned are the same hashing encoder, so the gate can never pass with it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from earthtrend.analytics.ml.varsearch import (
    ACTIVE_FILE,
    MODEL_NAME,
    Retriever,
    models_root,
    read_gates,
)
from earthtrend.analytics.ml.varsearch_catalog import (
    VariableCatalog,
    catalog_hash,
    default_catalog_path,
    load_catalog,
)
from earthtrend.analytics.ml.varsearch_encoders import (
    E5_PASSAGE_PREFIX,
    E5_QUERY_PREFIX,
    Encoder,
    HashingEncoder,
    SentenceTransformerEncoder,
)
from earthtrend.analytics.training.varsearch.dataset import build_dataset
from earthtrend.analytics.training.varsearch.evaluate import (
    EvalQuery,
    evaluate_systems,
    quality_gate,
)
from earthtrend.analytics.training.varsearch.generate import (
    LEXICON_PATH,
    GeneratorConfig,
    Pair,
    load_lexicon,
)
from earthtrend.analytics.training.varsearch.human_test import (
    HUMAN_TEST_DIR,
    MIN_PER_LANG,
    load_human_test,
    remove_overlap,
)
from earthtrend.analytics.training.varsearch.train import TrainConfig, fine_tune

EncoderKind = Literal["sentence-transformers", "hashing"]


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).parent,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _eval_queries_from_pairs(pairs: list[Pair]) -> list[EvalQuery]:
    return [EvalQuery(p.query, p.lang, tuple(p.relevant)) for p in pairs]


def systems_for(
    catalog: VariableCatalog, base: Encoder, tuned: Encoder, alpha: float
) -> dict[str, Retriever]:
    return {
        "bm25": Retriever(catalog, mode="bm25"),
        "base_dense": Retriever(catalog, base, mode="dense"),
        "base_hybrid": Retriever(catalog, base, mode="hybrid", alpha=alpha),
        "tuned_dense": Retriever(catalog, tuned, mode="dense"),
        "tuned_hybrid": Retriever(catalog, tuned, mode="hybrid", alpha=alpha),
    }


def evaluate_on_human(
    catalog: VariableCatalog,
    systems: dict[str, Retriever],
    training_queries: list[str],
    human_test_dir: Path = HUMAN_TEST_DIR,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """(metrics on the human test or None, gates.json)."""
    human = load_human_test(catalog, human_test_dir)
    if human is None:
        return None, quality_gate(None)
    kept, dropped = remove_overlap(human, training_queries)
    per_lang = {lang: sum(q.lang == lang for q in kept) for lang in ("en", "uk")}
    short = [f"{lang}={n}" for lang, n in per_lang.items() if n < MIN_PER_LANG]
    if short:
        gate = quality_gate(
            None,
            reason=f"human test too small (need >= {MIN_PER_LANG} per language): "
            + ", ".join(short),
        )
        return {"n_by_lang": per_lang, "dropped_overlap": dropped}, gate
    metrics = evaluate_systems(systems, [EvalQuery(q.query, q.lang, q.relevant) for q in kept])
    gate = quality_gate(metrics)
    gate["dropped_overlap_with_training"] = dropped
    return {"systems": metrics, "n_by_lang": per_lang, "dropped_overlap": dropped}, gate


def _fmt(m: dict[str, Any] | None) -> str:
    if not m or not m.get("n"):
        return "—"
    return f"{m['recall@5']:.3f} / {m['mrr']:.3f}"


def model_card(
    version: str,
    config: dict[str, Any],
    manifest: dict[str, Any],
    metrics: dict[str, Any],
    gates: dict[str, Any],
) -> str:
    dev = metrics["synthetic_dev"]
    rows = "\n".join(
        f"| {name} | {_fmt(m.get('en'))} | {_fmt(m.get('uk'))} |" for name, m in dev.items()
    )
    human = metrics.get("human_test")
    if human and "systems" in human:
        hrows = "\n".join(
            f"| {name} | {_fmt(m.get('en'))} | {_fmt(m.get('uk'))} |"
            for name, m in human["systems"].items()
        )
        human_block = f"| system | EN R@5 / MRR | UA R@5 / MRR |\n|---|---|---|\n{hrows}"
    else:
        human_block = "Not evaluated: " + str(gates.get("reason"))
    enc = config["encoder"]
    return f"""# M3 VarSearch «Пошуковик» — model card, version `{version}`

**Purpose.** Find catalog variables from a free-text query in Ukrainian or English
("чи стає сухіше", "air pollution"). Advisory search only; it never produces evidence.

**Model.** Encoder `{enc["kind"]}`, base `{enc.get("base_model", "—")}`, fine-tuned contrastively
(MultipleNegativesRankingLoss, hard negatives). Served as a hybrid with BM25
(alpha = {config["fusion"]["alpha"]}). Code commit `{config["git_commit"]}`.

**Data.** {manifest["counts"]["train"]["n"]} training / {manifest["counts"]["dev"]["n"]} dev
pairs, generated from templates × a hand-written lexicon ({manifest["generator_version"]},
{manifest["lexicon_version"]}), catalog `{manifest["catalog_version"]}`
(hash `{manifest["catalog_hash"][:12]}`). No LLM, no user logs.

**Gate (PLAN_ANALYTICS 11.4).** Overall: **{gates["overall"]}**. Requirement: tuned hybrid
beats base model + BM25 by ≥ {gates["margin"] * 100:.0f} pp in Recall@5 and MRR, separately
for UA and EN, on the human-written test. The app serves the model only when this is `pass`.

## Human test (the only numbers that decide shipping)
{human_block}

## Synthetic dev set (sanity check only — same generator as training, optimistic)
| system | EN R@5 / MRR | UA R@5 / MRR |
|---|---|---|
{rows}

## Limitations
- Training queries are template-generated; real wording is more varied. Synthetic dev
  numbers overstate quality and must not be quoted as the product metric.
- The catalog is the starter list (~55 variables). New variables need regenerated pairs and
  retraining; until then the hybrid still finds them through BM25 and the base embedding.
- Phenomenon questions ("чи стає сухіше") have several valid answers; the model ranks
  them but cannot say which one the user meant.
- Weights are a sentence-transformers folder (PyTorch); ONNX export is a follow-up.
"""


def run(
    version: str,
    *,
    models_dir: Path | None = None,
    catalog_path: Path | None = None,
    encoder: EncoderKind = "sentence-transformers",
    train_config: TrainConfig | None = None,
    generator_config: GeneratorConfig | None = None,
    human_test_dir: Path = HUMAN_TEST_DIR,
    overwrite: bool = False,
) -> dict[str, Any]:
    tcfg = train_config or TrainConfig()
    gcfg = generator_config or GeneratorConfig(seed=tcfg.seed)
    cat_path = catalog_path or default_catalog_path()
    catalog = load_catalog(cat_path)
    lexicon = load_lexicon()
    root = models_root(models_dir) / MODEL_NAME
    vdir = root / version
    if vdir.exists():
        if not overwrite:
            raise FileExistsError(f"{vdir} exists (use overwrite=True)")
        shutil.rmtree(vdir)
    vdir.mkdir(parents=True)

    train, dev, manifest = build_dataset(
        vdir / "data",
        catalog,
        lexicon,
        config=gcfg,
        catalog_path=cat_path,
        lexicon_path=LEXICON_PATH,
        human_test_dir=human_test_dir,
    )

    base: Encoder
    tuned: Encoder
    enc_cfg: dict[str, Any]
    if encoder == "hashing":
        base = tuned = HashingEncoder()
        enc_cfg = {"kind": "hashing", "dim": 512}
    else:
        fine_tune(train, catalog, tcfg, vdir / "model")
        shutil.rmtree(vdir / "model" / "_checkpoints", ignore_errors=True)
        base = SentenceTransformerEncoder(tcfg.base_model, device=tcfg.device)
        tuned = SentenceTransformerEncoder(vdir / "model", device=tcfg.device)
        enc_cfg = {
            "kind": "sentence-transformers",
            "path": "model",
            "base_model": tcfg.base_model,
            "query_prefix": E5_QUERY_PREFIX,
            "passage_prefix": E5_PASSAGE_PREFIX,
        }

    systems = systems_for(catalog, base, tuned, tcfg.alpha)
    metrics: dict[str, Any] = {
        "synthetic_dev": evaluate_systems(systems, _eval_queries_from_pairs(dev)),
        "synthetic_dev_note": "generated like training; sanity check, not the gate",
    }
    human_metrics, gates = evaluate_on_human(
        catalog, systems, [p.query for p in train + dev], human_test_dir
    )
    metrics["human_test"] = human_metrics

    config: dict[str, Any] = {
        "model": MODEL_NAME,
        "version": version,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "encoder": enc_cfg,
        "fusion": {"kind": "hybrid", "alpha": tcfg.alpha},
        "train": asdict(tcfg),
        "generator": asdict(gcfg),
        "catalog_hash": catalog_hash(catalog),
    }
    (vdir / "config.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    shutil.copyfile(vdir / "data" / "data_manifest.json", vdir / "data_manifest.json")
    (vdir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (vdir / "gates.json").write_text(json.dumps(gates, indent=2), encoding="utf-8")
    (vdir / "model_card.md").write_text(
        model_card(version, config, manifest, metrics, gates), encoding="utf-8"
    )
    log = {
        "version": version,
        "created": config["created"],
        "git_commit": config["git_commit"],
        "data_hash": manifest["outputs"]["pairs_train.jsonl"],
        "config": config["train"],
        "gate": gates["overall"],
        "synthetic_dev": metrics["synthetic_dev"],
    }
    with (root / "experiments.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(log) + "\n")
    return {"version_dir": str(vdir), "metrics": metrics, "gates": gates}


def promote(version: str, models_dir: Path | None = None) -> Path:
    """Make `version` active. Refuses unless its gates.json says `pass` (11.6)."""
    root = models_root(models_dir) / MODEL_NAME
    gates = read_gates(root / version)
    status = (gates or {}).get("overall", "missing")
    if status != "pass":
        raise PermissionError(f"varsearch {version}: gate is {status!r}, not promoting")
    p = root / ACTIVE_FILE
    p.write_text(version + "\n", encoding="utf-8")
    return p
