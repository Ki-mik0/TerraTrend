"""CLI for M3 VarSearch (stand-in for `earthtrend ml ... varsearch`, PLAN_ANALYTICS 11.6).

    python -m earthtrend.analytics.training.varsearch build-dataset OUT_DIR
    python -m earthtrend.analytics.training.varsearch train VERSION [--epochs 2] [--hashing]
    python -m earthtrend.analytics.training.varsearch evaluate VERSION
    python -m earthtrend.analytics.training.varsearch promote VERSION

`train` runs the whole pipeline (dataset, fine-tune, evaluation, gate, artifacts). Needs the
optional `varsearch` dependency group unless `--hashing` is given.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from earthtrend.analytics.ml.varsearch import MODEL_NAME, models_root
from earthtrend.analytics.ml.varsearch_catalog import default_catalog_path, load_catalog


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="varsearch")
    ap.add_argument("--models-dir", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-dataset")
    b.add_argument("out_dir", type=Path)
    b.add_argument("--seed", type=int, default=13)
    t = sub.add_parser("train")
    t.add_argument("version")
    t.add_argument("--epochs", type=int, default=2)
    t.add_argument("--batch-size", type=int, default=16)
    t.add_argument("--base-model", default=None)
    t.add_argument("--device", default=None)
    t.add_argument("--seed", type=int, default=13)
    t.add_argument("--hashing", action="store_true", help="smoke run without torch")
    t.add_argument("--overwrite", action="store_true")
    e = sub.add_parser("evaluate")
    e.add_argument("version")
    p = sub.add_parser("promote")
    p.add_argument("version")
    args = ap.parse_args(argv)

    if args.cmd == "build-dataset":
        from earthtrend.analytics.training.varsearch.dataset import build_dataset
        from earthtrend.analytics.training.varsearch.generate import (
            LEXICON_PATH,
            GeneratorConfig,
            load_lexicon,
        )

        cat_path = default_catalog_path()
        _, _, manifest = build_dataset(
            args.out_dir,
            load_catalog(cat_path),
            load_lexicon(),
            config=GeneratorConfig(seed=args.seed),
            catalog_path=cat_path,
            lexicon_path=LEXICON_PATH,
        )
        print(json.dumps(manifest["counts"], indent=2))
        return 0

    if args.cmd == "train":
        from earthtrend.analytics.training.varsearch.pipeline import run
        from earthtrend.analytics.training.varsearch.train import DEFAULT_BASE_MODEL, TrainConfig

        cfg = TrainConfig(
            base_model=args.base_model or DEFAULT_BASE_MODEL,
            epochs=args.epochs,
            batch_size=args.batch_size,
            seed=args.seed,
            device=args.device,
        )
        out = run(
            args.version,
            models_dir=args.models_dir,
            train_config=cfg,
            encoder="hashing" if args.hashing else "sentence-transformers",
            overwrite=args.overwrite,
        )
        print(json.dumps({"dir": out["version_dir"], "gate": out["gates"]["overall"]}, indent=2))
        return 0

    if args.cmd == "evaluate":
        from earthtrend.analytics.ml.varsearch import load_encoder
        from earthtrend.analytics.ml.varsearch_encoders import Encoder
        from earthtrend.analytics.training.varsearch.dataset import read_pairs
        from earthtrend.analytics.training.varsearch.pipeline import (
            evaluate_on_human,
            model_card,
            systems_for,
        )

        vdir = models_root(args.models_dir) / MODEL_NAME / args.version
        config = yaml.safe_load((vdir / "config.yaml").read_text(encoding="utf-8"))
        catalog = load_catalog()
        tuned = load_encoder(vdir, config)
        if config["encoder"]["kind"] == "sentence-transformers":
            from earthtrend.analytics.ml.varsearch_encoders import SentenceTransformerEncoder

            base: Encoder = SentenceTransformerEncoder(config["encoder"]["base_model"])
        else:
            base = load_encoder(vdir, config)
        systems = systems_for(catalog, base, tuned, float(config["fusion"]["alpha"]))
        train = read_pairs(vdir / "data" / "pairs_train.jsonl")
        dev = read_pairs(vdir / "data" / "pairs_dev.jsonl")
        human, gates = evaluate_on_human(catalog, systems, [p.query for p in train + dev])
        metrics = json.loads((vdir / "metrics.json").read_text(encoding="utf-8"))
        metrics["human_test"] = human
        manifest = json.loads((vdir / "data_manifest.json").read_text(encoding="utf-8"))
        (vdir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        (vdir / "gates.json").write_text(json.dumps(gates, indent=2), encoding="utf-8")
        (vdir / "model_card.md").write_text(
            model_card(args.version, config, manifest, metrics, gates), encoding="utf-8"
        )
        print(json.dumps(gates, indent=2))
        return 0

    if args.cmd == "promote":
        from earthtrend.analytics.training.varsearch.pipeline import promote

        print(promote(args.version, args.models_dir))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
