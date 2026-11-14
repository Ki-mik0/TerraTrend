"""The human-written test set for M3 (PLAN_ANALYTICS 11.4): ~300 queries by people.

Only `human_test/human_test.csv` counts. The placeholder file next to it is an example of
the format and is never loaded as a test. Rows must say `source=human`; anything generated
(templates, LLM) is rejected, because the gate must measure real people's wording.
See `human_test/README.md` for how the team fills it in.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from earthtrend.analytics.ml.varsearch_catalog import LANGS, Lang, VariableCatalog
from earthtrend.analytics.ml.varsearch_lexical import normalize

HUMAN_TEST_DIR = Path(__file__).with_name("human_test")
HUMAN_TEST_FILE = "human_test.csv"
PLACEHOLDER_FILE = "human_test.PLACEHOLDER.csv"
COLUMNS = ("query", "lang", "relevant", "author_role", "source")
AUTHOR_ROLES = {"team", "student", "teacher", "scientist", "other"}
# Below this many queries per language the gate stays `not_evaluated`.
MIN_PER_LANG = 100


@dataclass(frozen=True)
class HumanQuery:
    query: str
    lang: Lang
    relevant: tuple[str, ...]
    author_role: str


class HumanTestError(ValueError):
    pass


def read_rows(path: Path, catalog: VariableCatalog) -> list[HumanQuery]:
    ids = set(catalog.ids)
    out: list[HumanQuery] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = set(COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise HumanTestError(f"{path.name}: missing columns {sorted(missing)}")
        for n, row in enumerate(reader, start=2):
            if row["source"].strip() != "human":
                raise HumanTestError(f"{path.name}:{n}: source must be 'human'")
            lang = row["lang"].strip()
            if lang not in LANGS:
                raise HumanTestError(f"{path.name}:{n}: lang must be en or uk")
            rel = tuple(r.strip() for r in row["relevant"].split(";") if r.strip())
            bad = [r for r in rel if r not in ids]
            if not rel or bad:
                raise HumanTestError(f"{path.name}:{n}: unknown or empty relevant ids {bad}")
            role = row["author_role"].strip()
            if role not in AUTHOR_ROLES:
                raise HumanTestError(f"{path.name}:{n}: author_role must be in {AUTHOR_ROLES}")
            q = row["query"].strip()
            if q:
                out.append(HumanQuery(q, lang, rel, role))
    return out


def load_human_test(
    catalog: VariableCatalog, directory: Path = HUMAN_TEST_DIR
) -> list[HumanQuery] | None:
    """The real human test set, or None while it does not exist yet."""
    path = directory / HUMAN_TEST_FILE
    if not path.is_file():
        return None
    return read_rows(path, catalog)


def remove_overlap(
    queries: list[HumanQuery], training_queries: list[str]
) -> tuple[list[HumanQuery], int]:
    """Drop human queries that also appear (normalized) among training queries."""
    seen = {" ".join(normalize(q).split()) for q in training_queries}
    kept = [q for q in queries if " ".join(normalize(q.query).split()) not in seen]
    return kept, len(queries) - len(kept)
