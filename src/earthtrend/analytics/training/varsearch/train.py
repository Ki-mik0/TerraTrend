"""Contrastive fine-tuning of the M3 embedding model (PLAN_ANALYTICS 11.4).

Loss: MultipleNegativesRankingLoss (Henderson et al. 2017; sentence-transformers) on
(query, positive passage, hard-negative passage) triplets: every other passage in the batch is
an extra negative. With ~55 variables, two rows of the same variable in one batch would be
false negatives, so batches use the NO_DUPLICATES sampler (no text twice per batch).

Heavy imports (torch, sentence-transformers, datasets) happen inside `fine_tune` only.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from earthtrend.analytics.ml.varsearch_catalog import VariableCatalog, passage_text
from earthtrend.analytics.ml.varsearch_encoders import E5_PASSAGE_PREFIX, E5_QUERY_PREFIX
from earthtrend.analytics.training.varsearch.generate import Pair

DEFAULT_BASE_MODEL = "intfloat/multilingual-e5-small"


@dataclass(frozen=True)
class TrainConfig:
    base_model: str = DEFAULT_BASE_MODEL
    epochs: int = 2
    batch_size: int = 16
    learning_rate: float = 2e-5
    warmup_ratio: float = 0.1
    max_seq_length: int = 192
    seed: int = 13
    use_hard_negatives: bool = True
    alpha: float = 0.7  # hybrid fusion weight of the dense score (fixed, not tuned on test)
    device: str | None = None


def triplets(
    pairs: list[Pair], catalog: VariableCatalog, *, hard_negatives: bool = True
) -> dict[str, list[str]]:
    docs = catalog.by_id()
    data: dict[str, list[str]] = {"anchor": [], "positive": []}
    if hard_negatives:
        data["negative"] = []
    for p in pairs:
        data["anchor"].append(E5_QUERY_PREFIX + p.query)
        data["positive"].append(E5_PASSAGE_PREFIX + passage_text(docs[p.positive]))
        if hard_negatives:
            data["negative"].append(E5_PASSAGE_PREFIX + passage_text(docs[p.hard_negative]))
    return data


def fine_tune(
    train_pairs: list[Pair], catalog: VariableCatalog, cfg: TrainConfig, out_dir: Path
) -> Path:
    """Train and save a sentence-transformers model to `out_dir`; returns `out_dir`."""
    import numpy as np
    import torch
    from datasets import Dataset
    from sentence_transformers import (
        SentenceTransformer,
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
        losses,
    )
    from sentence_transformers.training_args import BatchSamplers

    random.seed(cfg.seed)
    np.random.seed(cfg.seed)  # noqa: NPY002 - global seed for libraries that use it
    torch.manual_seed(cfg.seed)

    model = SentenceTransformer(cfg.base_model, device=cfg.device)
    model.max_seq_length = cfg.max_seq_length
    dataset = Dataset.from_dict(
        triplets(train_pairs, catalog, hard_negatives=cfg.use_hard_negatives)
    ).shuffle(seed=cfg.seed)
    loss = losses.MultipleNegativesRankingLoss(model)
    args = SentenceTransformerTrainingArguments(
        output_dir=str(out_dir / "_checkpoints"),
        num_train_epochs=cfg.epochs,
        per_device_train_batch_size=cfg.batch_size,
        learning_rate=cfg.learning_rate,
        warmup_ratio=cfg.warmup_ratio,
        batch_sampler=BatchSamplers.NO_DUPLICATES,
        seed=cfg.seed,
        save_strategy="no",
        logging_steps=50,
        report_to=[],
    )
    trainer = SentenceTransformerTrainer(model=model, args=args, train_dataset=dataset, loss=loss)
    trainer.train()
    model.save(str(out_dir))
    return out_dir
