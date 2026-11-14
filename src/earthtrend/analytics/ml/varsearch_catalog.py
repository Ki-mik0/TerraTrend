"""Variable catalog as seen by M3 VarSearch (PLAN_ANALYTICS 11.4).

The backend owns the real passport catalog (CatalogPort). Search only needs a few fields
per variable, so this module defines that minimal view and a loader for the starter
catalog `catalog/variables_starter.yaml`. Only stdlib, pydantic and PyYAML: the app must be
able to search without any ML dependency installed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Lang = Literal["en", "uk"]
LANGS: tuple[Lang, ...] = ("en", "uk")


class LocalizedText(BaseModel):
    model_config = ConfigDict(frozen=True)
    en: str
    uk: str

    def get(self, lang: Lang) -> str:
        return self.en if lang == "en" else self.uk


class LocalizedList(BaseModel):
    model_config = ConfigDict(frozen=True)
    en: list[str] = Field(default_factory=list)
    uk: list[str] = Field(default_factory=list)

    def get(self, lang: Lang) -> list[str]:
        return self.en if lang == "en" else self.uk


class VariableDoc(BaseModel):
    """The searchable part of a variable passport."""

    model_config = ConfigDict(frozen=True)
    id: str
    concept: str
    theme: str
    domain: str
    seasonal: bool = False
    source: str = ""
    units: str = ""
    names: LocalizedText
    descriptions: LocalizedText
    keywords: LocalizedList = Field(default_factory=LocalizedList)
    confusable_with: list[str] = Field(default_factory=list)


class VariableCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str
    variables: list[VariableDoc]

    @model_validator(mode="after")
    def _check_ids(self) -> VariableCatalog:
        ids = [v.id for v in self.variables]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"duplicate variable ids: {sorted(dup)}")
        known = set(ids)
        for v in self.variables:
            bad = [c for c in v.confusable_with if c not in known or c == v.id]
            if bad:
                raise ValueError(f"{v.id}: confusable_with has unknown/self ids {bad}")
        return self

    @property
    def ids(self) -> list[str]:
        return [v.id for v in self.variables]

    def by_id(self) -> dict[str, VariableDoc]:
        return {v.id: v for v in self.variables}

    def same_concept(self, var_id: str) -> list[str]:
        """Ids sharing the concept of `var_id` (including itself)."""
        concept = self.by_id()[var_id].concept
        return [v.id for v in self.variables if v.concept == concept]


def default_catalog_path() -> Path:
    """`catalog/variables_starter.yaml` at the repository root (source checkouts only)."""
    return Path(__file__).resolve().parents[4] / "catalog" / "variables_starter.yaml"


def load_catalog(path: str | Path | None = None) -> VariableCatalog:
    p = Path(path) if path is not None else default_catalog_path()
    with p.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return VariableCatalog.model_validate(raw)


def catalog_hash(catalog: VariableCatalog) -> str:
    """sha256 of the canonical JSON form; recorded in data manifests and model configs."""
    blob = json.dumps(catalog.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def passage_text(doc: VariableDoc) -> str:
    """Bilingual text of a variable for the embedding model (both languages in one passage,
    so a UA query and an EN query land on the same vector)."""
    return (
        f"{doc.names.en}. {doc.names.uk}. {doc.descriptions.en} {doc.descriptions.uk} "
        f"{', '.join(doc.keywords.en)}. {', '.join(doc.keywords.uk)}."
    )
