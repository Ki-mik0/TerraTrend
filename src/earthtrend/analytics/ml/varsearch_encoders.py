"""Text encoders for M3 VarSearch.

* `HashingEncoder` - deterministic character-trigram hashing; no download, no torch. Used by
  tests and as a smoke-test encoder for the whole pipeline. Not a product model.
* `SentenceTransformerEncoder` - the real model (base `multilingual-e5-small` or a fine-tuned
  copy). Imports `sentence_transformers` lazily, so the core package never needs it.

All encoders return L2-normalized float32 rows, so a dot product is the cosine similarity.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np

from earthtrend.analytics.ml.varsearch_lexical import trigram_tokens

TextKind = Literal["query", "passage"]

E5_QUERY_PREFIX = "query: "
E5_PASSAGE_PREFIX = "passage: "


class Encoder(Protocol):
    name: str

    def encode(self, texts: Sequence[str], kind: TextKind) -> np.ndarray: ...


def _l2(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=1, keepdims=True)
    return (x / np.where(n > 0, n, 1.0)).astype(np.float32)


class HashingEncoder:
    """Bag of character trigrams hashed into `dim` buckets (signed), L2-normalized."""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.name = f"hashing-trigram-{dim}"

    def encode(self, texts: Sequence[str], kind: TextKind) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float64)
        for i, text in enumerate(texts):
            for tok in trigram_tokens(text):
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
                out[i, h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        return _l2(out)


class SentenceTransformerEncoder:
    """Wrapper over a sentence-transformers model with e5-style query/passage prefixes."""

    def __init__(
        self,
        model_name_or_path: str | Path,
        *,
        query_prefix: str = E5_QUERY_PREFIX,
        passage_prefix: str = E5_PASSAGE_PREFIX,
        device: str | None = None,
        batch_size: int = 64,
        model: Any = None,
    ) -> None:
        if model is None:
            from sentence_transformers import SentenceTransformer  # heavy, optional

            model = SentenceTransformer(str(model_name_or_path), device=device)
        self.model = model
        self.name = str(model_name_or_path)
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self.batch_size = batch_size

    def encode(self, texts: Sequence[str], kind: TextKind) -> np.ndarray:
        prefix = self.query_prefix if kind == "query" else self.passage_prefix
        emb = self.model.encode(
            [prefix + t for t in texts],
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(emb, dtype=np.float32)
