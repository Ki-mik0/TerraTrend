"""Lexical search for M3: BM25 over the catalog, UA/EN, robust to inflection and typos.

This is both the fallback search (no model, or the model failed its gate) and the lexical
half of the hybrid. Pure numpy, no `rank-bm25`, so it runs in the core package.

Two BM25 fields are scored and mixed:
* word stems - lowercase, apostrophes unified, light suffix stripping, then truncation to
  `STEM_LEN` characters, so "температура / температури / температурі" all match;
* character trigrams of every word - catch typos ("temperatrue") and wrong word forms.

BM25 (Robertson & Zaragoza 2009): idf = ln(1 + (N - df + 0.5) / (df + 0.5)),
score = sum idf * tf (k1 + 1) / (tf + k1 (1 - b + b |d| / avgdl)).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

import numpy as np

from earthtrend.analytics.ml.varsearch_catalog import VariableCatalog, VariableDoc

STEM_LEN = 6
TRIGRAM_WEIGHT = 0.5
NAME_BOOST = 2  # names are repeated this many times in the stem field

_WORD = re.compile(r"[\w]+", re.UNICODE)
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "´": "'"})
# Longest first. Light, language-agnostic: good enough for retrieval, not linguistics.
_SUFFIXES = sorted(
    {
        # en
        "ing",
        "ed",
        "es",
        "s",
        "ly",
        "ness",
        "ation",
        "ations",
        # uk
        "ами",
        "ями",
        "ові",
        "еві",
        "ого",
        "ому",
        "ими",
        "ій",
        "ий",
        "ої",
        "их",
        "им",
        "ою",
        "ею",
        "ях",
        "ах",
        "ів",
        "ам",
        "ям",
        "ом",
        "ем",
        "ти",
        "ть",
        "ся",
        "а",
        "я",
        "у",
        "ю",
        "і",
        "и",
        "е",
        "о",
    },
    key=len,
    reverse=True,
)
_STOP = {
    # en
    "the",
    "a",
    "an",
    "of",
    "in",
    "on",
    "at",
    "for",
    "to",
    "and",
    "or",
    "is",
    "are",
    "it",
    "how",
    "what",
    "show",
    "me",
    "over",
    "since",
    "data",
    "trend",
    "trends",
    "map",
    "time",
    "series",
    "with",
    "from",
    "by",
    "do",
    "does",
    "did",
    "has",
    "have",
    # uk
    "і",
    "й",
    "та",
    "в",
    "у",
    "на",
    "з",
    "із",
    "зі",
    "за",
    "до",
    "про",
    "чи",
    "як",
    "що",
    "це",
    "для",
    "по",
    "від",
    "покажи",
    "дані",
    "тренд",
    "тренди",
    "карта",
    "ряд",
    "над",
    "під",
    "роки",
    "років",
    "року",
}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower().translate(_APOSTROPHES)
    return t.replace("'", "")


def stem(word: str) -> str:
    if word.isdigit() or len(word) <= 3:
        return word
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            word = word[: -len(suf)]
            break
    return word[:STEM_LEN]


def words(text: str) -> list[str]:
    return _WORD.findall(normalize(text))


def stem_tokens(text: str) -> list[str]:
    return [stem(w) for w in words(text) if w not in _STOP]


def trigram_tokens(text: str) -> list[str]:
    out: list[str] = []
    for w in words(text):
        if w in _STOP:
            continue
        padded = f"#{w}#"
        out.extend(padded[i : i + 3] for i in range(len(padded) - 2))
    return out


class BM25:
    """Okapi BM25 over pre-tokenized documents."""

    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.tf = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=np.float64)
        self.avgdl = float(self.len.mean()) if self.n else 0.0
        df: Counter[str] = Counter()
        for c in self.tf:
            df.update(c.keys())
        self.idf = {t: float(np.log1p((self.n - f + 0.5) / (f + 0.5))) for t, f in df.items()}

    def scores(self, query: Sequence[str]) -> np.ndarray:
        out = np.zeros(self.n, dtype=np.float64)
        if not self.n:
            return out
        norm = self.k1 * (1.0 - self.b + self.b * self.len / max(self.avgdl, 1e-9))
        for term in set(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            tf = np.array([c.get(term, 0) for c in self.tf], dtype=np.float64)
            out += idf * tf * (self.k1 + 1.0) / (tf + norm)
        return out


def _doc_text(doc: VariableDoc) -> tuple[str, str]:
    names = f"{doc.names.en} {doc.names.uk}"
    body = (
        f"{doc.descriptions.en} {doc.descriptions.uk} "
        f"{' '.join(doc.keywords.en)} {' '.join(doc.keywords.uk)} {doc.source}"
    )
    return names, body


def _unit_max(x: np.ndarray) -> np.ndarray:
    m = float(x.max()) if x.size else 0.0
    return x / m if m > 0 else np.zeros_like(x)


class LexicalSearcher:
    """BM25 stems + BM25 character trigrams over a catalog; scores in [0, 1 + TRIGRAM_WEIGHT]."""

    def __init__(self, catalog: VariableCatalog) -> None:
        self.ids = catalog.ids
        stem_docs, tri_docs = [], []
        for doc in catalog.variables:
            names, body = _doc_text(doc)
            stem_docs.append(stem_tokens(names) * NAME_BOOST + stem_tokens(body))
            tri_docs.append(trigram_tokens(names) + trigram_tokens(body))
        self._stems = BM25(stem_docs)
        self._tri = BM25(tri_docs)

    def scores(self, query: str) -> np.ndarray:
        s = _unit_max(self._stems.scores(stem_tokens(query)))
        t = _unit_max(self._tri.scores(trigram_tokens(query)))
        return s + TRIGRAM_WEIGHT * t
