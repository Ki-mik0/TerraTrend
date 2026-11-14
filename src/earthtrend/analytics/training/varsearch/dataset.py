"""Build and hash the M3 training set (PLAN_ANALYTICS 11.6, `earthtrend ml build-dataset`).

Writes `pairs_train.jsonl`, `pairs_dev.jsonl` and `data_manifest.json` (hashes of every
input and output file, versions, the split rule and counts) into a directory.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from earthtrend.analytics.ml.varsearch_catalog import VariableCatalog, catalog_hash
from earthtrend.analytics.training.varsearch.generate import (
    GENERATOR_VERSION,
    GeneratorConfig,
    Lexicon,
    Pair,
    check_lexicon,
    generate_pairs,
)
from earthtrend.analytics.training.varsearch.human_test import (
    HUMAN_TEST_DIR,
    HUMAN_TEST_FILE,
)

SPLIT_RULE = (
    "dev = template id or synonym term in a held-out sha256 bucket "
    "(templates 20%, terms 15%, phenomenon questions 25%); catalog names always train. "
    "The human test (human_test/human_test.csv) is separate and never generated."
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_pairs(path: Path, pairs: list[Pair]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for p in pairs:
            fh.write(json.dumps(p.to_json(), ensure_ascii=False) + "\n")


def read_pairs(path: Path) -> list[Pair]:
    with path.open(encoding="utf-8") as fh:
        return [Pair(**json.loads(line)) for line in fh if line.strip()]


def _counts(pairs: list[Pair]) -> dict[str, Any]:
    return {
        "n": len(pairs),
        "by_lang": dict(Counter(p.lang for p in pairs)),
        "by_style": dict(Counter(p.style for p in pairs)),
        "with_typo": sum("typo" in p.noise for p in pairs),
        "variables": len({p.positive for p in pairs}),
    }


def build_dataset(
    out_dir: Path,
    catalog: VariableCatalog,
    lexicon: Lexicon,
    *,
    config: GeneratorConfig | None = None,
    catalog_path: Path | None = None,
    lexicon_path: Path | None = None,
    human_test_dir: Path = HUMAN_TEST_DIR,
) -> tuple[list[Pair], list[Pair], dict[str, Any]]:
    """Generate, split, write and hash. Returns (train, dev, manifest)."""
    problems = check_lexicon(lexicon, catalog)
    if problems:
        raise ValueError("lexicon does not match catalog: " + "; ".join(problems[:10]))
    cfg = config or GeneratorConfig()
    pairs = generate_pairs(catalog, lexicon, cfg)
    train = [p for p in pairs if p.split == "train"]
    dev = [p for p in pairs if p.split == "dev"]
    out_dir.mkdir(parents=True, exist_ok=True)
    write_pairs(out_dir / "pairs_train.jsonl", train)
    write_pairs(out_dir / "pairs_dev.jsonl", dev)
    human = human_test_dir / HUMAN_TEST_FILE
    manifest: dict[str, Any] = {
        "model": "varsearch",
        "generator_version": GENERATOR_VERSION,
        "generator_config": asdict(cfg),
        "lexicon_version": lexicon.version,
        "catalog_version": catalog.version,
        "catalog_hash": catalog_hash(catalog),
        "inputs": {
            "catalog_file_sha256": sha256_file(catalog_path) if catalog_path else None,
            "lexicon_file_sha256": sha256_file(lexicon_path) if lexicon_path else None,
            "human_test_sha256": sha256_file(human) if human.is_file() else None,
        },
        "outputs": {
            "pairs_train.jsonl": sha256_file(out_dir / "pairs_train.jsonl"),
            "pairs_dev.jsonl": sha256_file(out_dir / "pairs_dev.jsonl"),
        },
        "split_rule": SPLIT_RULE,
        "counts": {"train": _counts(train), "dev": _counts(dev)},
        "query_origin": "templates x hand-written lexicon (no LLM); not a human test",
    }
    (out_dir / "data_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return train, dev, manifest
