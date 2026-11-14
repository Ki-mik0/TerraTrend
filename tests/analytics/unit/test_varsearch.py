"""M3 VarSearch (stage A10): catalog, BM25 fallback, inference modes, pair generator,
human test loader, metrics and the quality gate. Fast: no model downloads, no torch."""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from earthtrend.analytics.ml.varsearch import (
    Retriever,
    VarSearch,
    fuse,
    search_variables,
)
from earthtrend.analytics.ml.varsearch_catalog import (
    VariableCatalog,
    catalog_hash,
    load_catalog,
    passage_text,
)
from earthtrend.analytics.ml.varsearch_encoders import HashingEncoder
from earthtrend.analytics.ml.varsearch_lexical import BM25, stem_tokens, trigram_tokens
from earthtrend.analytics.training.varsearch.evaluate import (
    EvalQuery,
    evaluate_retriever,
    quality_gate,
    recall_at_k,
    reciprocal_rank,
)
from earthtrend.analytics.training.varsearch.generate import (
    TEMPLATES,
    GeneratorConfig,
    add_noise,
    check_lexicon,
    generate_pairs,
    load_lexicon,
    typo,
    wrong_layout,
)
from earthtrend.analytics.training.varsearch.human_test import (
    HUMAN_TEST_DIR,
    PLACEHOLDER_FILE,
    HumanTestError,
    load_human_test,
    read_rows,
    remove_overlap,
)


@pytest.fixture(scope="module")
def catalog() -> VariableCatalog:
    return load_catalog()


@pytest.fixture(scope="module")
def bm25(catalog: VariableCatalog) -> VarSearch:
    return VarSearch(catalog)


@pytest.fixture(scope="module")
def pairs(catalog: VariableCatalog) -> list:
    return generate_pairs(catalog, load_lexicon())


def _top(s: VarSearch, q: str, k: int = 5) -> list[str]:
    return [h.id for h in s.search(q, page_size=k).items]


# ---------------------------------------------------------------- catalog


def test_starter_catalog(catalog: VariableCatalog) -> None:
    assert 40 <= len(catalog.variables) <= 80
    for v in catalog.variables:
        assert v.names.en and v.names.uk and v.descriptions.en and v.descriptions.uk
        assert v.keywords.en and v.keywords.uk
    assert set(catalog.same_concept("precipitation_imerg")) == {
        "precipitation_imerg",
        "precipitation_gpcp",
    }
    assert len(catalog_hash(catalog)) == 64
    assert "Опади" in passage_text(catalog.by_id()["precipitation_imerg"])


def test_catalog_validation() -> None:
    doc = {
        "id": "a",
        "concept": "c",
        "theme": "t",
        "domain": "d",
        "names": {"en": "A", "uk": "А"},
        "descriptions": {"en": "x", "uk": "х"},
    }
    with pytest.raises(ValueError, match="duplicate"):
        VariableCatalog.model_validate({"version": "v", "variables": [doc, doc]})
    with pytest.raises(ValueError, match="confusable_with"):
        VariableCatalog.model_validate(
            {"version": "v", "variables": [dict(doc, confusable_with=["zzz"])]}
        )


# ---------------------------------------------------------------- lexical / BM25


def test_tokenizers_handle_inflection_and_apostrophe() -> None:
    assert stem_tokens("температура")[0] == stem_tokens("температури")[0]
    assert stem_tokens("об’ємна") == stem_tokens("об'ємна")
    assert stem_tokens("trend of the rainfall") == stem_tokens("rainfall")
    assert "#te" in trigram_tokens("temperature")


def test_bm25_formula_small() -> None:
    idx = BM25([["a", "b"], ["b", "c", "c"], ["d"]])
    s = idx.scores(["c"])
    assert s[1] > 0 and s[0] == 0 and s[2] == 0
    assert np.all(idx.scores(["zzz"]) == 0)
    # rarer term has larger idf
    assert idx.idf["a"] > idx.idf["b"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("air pollution", {"pm25", "aerosol_optical_depth", "nitrogen_dioxide"}),
        ("зеленість лісів", {"ndvi", "evi"}),
        ("опади", {"precipitation_imerg", "precipitation_gpcp"}),
        ("температури повітря", {"air_temperature_2m"}),
        ("temperatrue", {"air_temperature_2m"}),  # typo, via trigrams
        ("лісові пожежі", {"fire_count", "burned_area"}),
        ("sea ice Arctic", {"sea_ice_concentration"}),
        ("NO2", {"nitrogen_dioxide"}),
    ],
)
def test_bm25_fallback_finds(bm25: VarSearch, query: str, expected: set[str]) -> None:
    assert expected & set(_top(bm25, query))


def test_search_page_contract(bm25: VarSearch, catalog: VariableCatalog) -> None:
    p = bm25.search("temperature", page_size=3)
    assert p.method == "bm25" and p.fallback_reason == "no_model" and p.model_version is None
    assert [h.rank for h in p.items] == [1, 2, 3]
    assert p.total >= 3
    assert all(a.score >= b.score for a, b in zip(p.items, p.items[1:], strict=False))
    p2 = bm25.search("temperature", page=2, page_size=3)
    assert p2.items[0].rank == 4
    assert {h.id for h in p.items}.isdisjoint({h.id for h in p2.items})
    # filters
    ocean = bm25.search("temperature", domain="ocean")
    assert ocean.items and all(catalog.by_id()[h.id].domain == "ocean" for h in ocean.items)
    seasonal = bm25.search("snow", seasonal=True)
    assert all(catalog.by_id()[h.id].seasonal for h in seasonal.items)
    only = bm25.search("temperature", allowed_ids={"sea_surface_temperature"})
    assert [h.id for h in only.items] == ["sea_surface_temperature"]
    assert bm25.search("temperature", theme="vegetation").total == 0
    # empty query: catalog order
    empty = bm25.search("", theme="air_quality", page_size=100)
    assert empty.method == "catalog"
    assert [h.id for h in empty.items] == [
        v.id for v in catalog.variables if v.theme == "air_quality"
    ]
    # gibberish: nothing rather than random variables
    assert bm25.search("qqqqzzzz").total == 0
    with pytest.raises(ValueError):
        bm25.search("x", page=0)


def test_search_variables_entry_point(bm25: VarSearch) -> None:
    p = search_variables("precipitation", searcher=bm25, page_size=2)
    assert p.items[0].id in {"precipitation_imerg", "precipitation_gpcp"}


# ---------------------------------------------------------------- inference modes


def test_fuse() -> None:
    d = np.array([0.2, 0.8, 0.5])
    lx = np.array([0.0, 0.0, 3.0])
    out = fuse(d, lx, alpha=0.5)
    assert out.argmax() == 2
    assert np.allclose(fuse(d, np.zeros(3), alpha=1.0), (d - 0.2) / 0.6)


def test_hybrid_and_dense_retriever(catalog: VariableCatalog) -> None:
    enc = HashingEncoder()
    hyb = Retriever(catalog, enc, mode="hybrid")
    dense = Retriever(catalog, enc, mode="dense")
    assert hyb.scores("sea surface temperature").shape == (len(catalog.variables),)
    assert hyb.rank_many(["sea surface temperature"])[0][0] == "sea_surface_temperature"
    assert dense.rank_many(["Sea surface temperature"])[0][0] == "sea_surface_temperature"
    # deterministic
    assert np.array_equal(enc.encode(["abc"], "query"), enc.encode(["abc"], "query"))
    with pytest.raises(ValueError):
        Retriever(catalog, None, mode="dense")


def _model_dir(root: Path, version: str, gate: str | None, active: bool = True) -> Path:
    vdir = root / "varsearch" / version
    vdir.mkdir(parents=True)
    cfg = {"encoder": {"kind": "hashing", "dim": 256}, "fusion": {"alpha": 0.6}}
    (vdir / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    if gate is not None:
        (vdir / "gates.json").write_text(json.dumps({"overall": gate}), encoding="utf-8")
    if active:
        (root / "varsearch" / "ACTIVE").write_text(version, encoding="utf-8")
    return vdir


def test_falls_back_without_model(tmp_path: Path, catalog: VariableCatalog) -> None:
    s = VarSearch.from_models_dir(catalog, tmp_path)
    assert s.mode == "bm25" and s.fallback_reason == "no_active_model"


@pytest.mark.parametrize("gate", ["fail", "not_evaluated", None])
def test_falls_back_when_gate_not_passed(
    tmp_path: Path, catalog: VariableCatalog, gate: str | None
) -> None:
    _model_dir(tmp_path, "0.1.0", gate)
    s = VarSearch.from_models_dir(catalog, tmp_path)
    assert s.mode == "bm25"
    assert s.fallback_reason == f"gate_{gate or 'missing'}:0.1.0"
    # explicit experiments may bypass the gate, the product default never does
    assert VarSearch.from_models_dir(catalog, tmp_path, allow_ungated=True).mode == "hybrid"


def test_uses_model_when_gate_passed(tmp_path: Path, catalog: VariableCatalog) -> None:
    _model_dir(tmp_path, "0.2.0", "pass")
    s = VarSearch.from_models_dir(catalog, tmp_path)
    assert s.mode == "hybrid" and s.model_version == "0.2.0" and s.retriever.alpha == 0.6
    p = s.search("sea surface temperature", page_size=3)
    assert p.method == "hybrid" and p.model_version == "0.2.0" and p.fallback_reason is None
    assert p.items[0].id == "sea_surface_temperature"


def test_falls_back_on_missing_dependency(
    tmp_path: Path, catalog: VariableCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    vdir = _model_dir(tmp_path, "0.3.0", "pass")
    cfg = {"encoder": {"kind": "sentence-transformers", "path": "model"}}
    (vdir / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # import -> ImportError
    s = VarSearch.from_models_dir(catalog, tmp_path)
    assert s.mode == "bm25"
    assert s.fallback_reason == "dependency_missing:sentence-transformers"


def test_core_does_not_import_heavy_deps() -> None:
    code = (
        "import sys, earthtrend.analytics.ml.varsearch, "
        "earthtrend.analytics.training.varsearch.pipeline as p;"
        "from earthtrend.analytics.ml.varsearch_catalog import load_catalog;"
        "from earthtrend.analytics.ml.varsearch import VarSearch;"
        "VarSearch(load_catalog()).search('rain');"
        "bad = {'torch', 'sentence_transformers', 'transformers', 'datasets'} & set(sys.modules);"
        "sys.exit(1 if bad else 0)"
    )
    src = str(Path(__file__).resolve().parents[3] / "src")
    out = subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": src})
    assert out.returncode == 0


# ---------------------------------------------------------------- generator


def test_lexicon_matches_catalog(catalog: VariableCatalog) -> None:
    assert check_lexicon(load_lexicon(), catalog) == []


def test_pairs_cover_languages_styles_and_noise(pairs: list, catalog: VariableCatalog) -> None:
    assert len(pairs) > 2000
    assert {p.lang for p in pairs} == {"en", "uk"}
    assert {p.style for p in pairs} >= {"school", "scientist", "casual", "phenomenon", "name"}
    assert {p.positive for p in pairs} == set(catalog.ids)
    typos = sum("typo" in p.noise for p in pairs) / len(pairs)
    assert 0.15 < typos < 0.45
    for p in pairs:
        assert p.positive in p.relevant
        assert p.hard_negative not in p.relevant
        assert "{" not in p.query  # every template slot filled
    by = catalog.by_id()
    conf = [p for p in pairs if p.hard_negative in by[p.positive].confusable_with]
    assert len(conf) / len(pairs) > 0.6  # hard negatives mostly from confusable_with


def test_pairs_deterministic_and_seeded(catalog: VariableCatalog, pairs: list) -> None:
    lex = load_lexicon()
    again = generate_pairs(catalog, lex)
    assert [p.query for p in again] == [p.query for p in pairs]
    other = generate_pairs(catalog, lex, GeneratorConfig(seed=99))
    assert [p.query for p in other] != [p.query for p in pairs]


def test_split_holds_out_templates(pairs: list) -> None:
    train = [p for p in pairs if p.split == "train"]
    dev = [p for p in pairs if p.split == "dev"]
    assert 0.1 < len(dev) / len(pairs) < 0.45
    assert all(p.split == "train" for p in pairs if p.style == "name")
    dev_only_tpl = {p.template_id for p in dev} - {p.template_id for p in train}
    assert dev_only_tpl  # some templates never seen in training
    assert {p.lang for p in dev} == {"en", "uk"}


def test_relevance_same_concept_unless_product_named(pairs: list) -> None:
    # relevance is decided on the clean text (before typos), i.e. on the term
    generic = [
        p
        for p in pairs
        if p.positive == "precipitation_imerg"
        and "imerg" not in p.term.lower()
        and "gpm" not in p.term.lower()
        and p.source == "template"
    ]
    named = [p for p in pairs if p.positive == "precipitation_imerg" and "imerg" in p.term.lower()]
    assert generic and all(
        set(p.relevant) == {"precipitation_imerg", "precipitation_gpcp"} for p in generic
    )
    assert named and all(p.relevant == ["precipitation_imerg"] for p in named)


def test_noise_functions() -> None:
    rng = random.Random(0)
    assert typo("температура", "uk", rng) != "температура"
    assert typo("a b c", "en", rng) == "a b c"  # nothing long enough to edit
    assert wrong_layout("температура") == "ntvgthfnehf"
    text, applied = add_noise("Soil moisture", "en", random.Random(3))
    assert isinstance(text, str) and set(applied) <= {"typo", "lower", "layout"}


def test_templates_well_formed() -> None:
    ids = [t.id for t in TEMPLATES]
    assert len(ids) == len(set(ids))
    for t in TEMPLATES:
        assert "{t}" in t.text or "{g}" in t.text
        assert t.id.startswith(t.lang)


# ---------------------------------------------------------------- human test


def test_human_test_missing_means_none(tmp_path: Path, catalog: VariableCatalog) -> None:
    assert load_human_test(catalog, tmp_path) is None


def test_placeholder_is_never_the_human_test(catalog: VariableCatalog) -> None:
    assert (HUMAN_TEST_DIR / PLACEHOLDER_FILE).is_file()
    assert (HUMAN_TEST_DIR / "README.md").is_file()
    # format of the placeholder is valid, but the loader ignores the file
    rows = read_rows(HUMAN_TEST_DIR / PLACEHOLDER_FILE, catalog)
    assert {r.lang for r in rows} == {"en", "uk"}
    if not (HUMAN_TEST_DIR / "human_test.csv").is_file():
        assert load_human_test(catalog) is None


def _csv(path: Path, rows: list[str]) -> Path:
    path.write_text(
        "query,lang,relevant,author_role,source\n" + "\n".join(rows) + "\n", encoding="utf-8"
    )
    return path


def test_human_test_rejects_generated_or_bad_rows(tmp_path: Path, catalog: VariableCatalog) -> None:
    with pytest.raises(HumanTestError, match="source"):
        read_rows(_csv(tmp_path / "a.csv", ["x,en,ndvi,team,llm"]), catalog)
    with pytest.raises(HumanTestError, match="unknown"):
        read_rows(_csv(tmp_path / "b.csv", ["x,en,not_a_var,team,human"]), catalog)
    with pytest.raises(HumanTestError, match="lang"):
        read_rows(_csv(tmp_path / "c.csv", ["x,de,ndvi,team,human"]), catalog)
    ok = read_rows(_csv(tmp_path / "d.csv", ["Green Forests,en,ndvi;evi,student,human"]), catalog)
    kept, dropped = remove_overlap(ok, ["green  forests"])
    assert kept == [] and dropped == 1


# ---------------------------------------------------------------- metrics and gate


def test_metrics_by_hand() -> None:
    assert recall_at_k(["a", "b", "c"], ["c"], k=2) == 0.0
    assert recall_at_k(["a", "b", "c"], ["c", "x"], k=3) == 1.0
    assert reciprocal_rank(["a", "b", "c"], ["b", "c"]) == 0.5
    assert reciprocal_rank(["a"], ["z"]) == 0.0


def test_evaluate_retriever_per_language(catalog: VariableCatalog) -> None:
    r = Retriever(catalog, mode="bm25")
    qs = [
        EvalQuery("ndvi", "en", ("ndvi",)),
        EvalQuery("озон", "uk", ("total_ozone",)),
        EvalQuery("qqqq", "uk", ("ndvi",)),
    ]
    m = evaluate_retriever(r, qs)
    assert m["en"]["n"] == 1 and m["en"]["recall@1"] == 1.0
    assert m["uk"]["n"] == 2 and m["all"]["n"] == 3
    assert 0.5 <= m["uk"]["recall@5"] <= 1.0


def _metrics(base: float, cand: float, cand_uk: float | None = None) -> dict:
    def block(x: float, y: float) -> dict:
        return {"n": 150, "recall@5": x, "mrr": y}

    uk = cand if cand_uk is None else cand_uk
    return {
        "base_hybrid": {"en": block(base, base), "uk": block(base, base)},
        "tuned_hybrid": {"en": block(cand, cand), "uk": block(uk, uk)},
    }


def test_gate_not_evaluated_without_human_test() -> None:
    g = quality_gate(None)
    assert g["overall"] == "not_evaluated" and "human" in g["reason"]


def test_gate_pass_and_fail() -> None:
    assert quality_gate(_metrics(0.70, 0.76))["overall"] == "pass"
    # +5 pp in EN but only +3 pp in UA: fails (separately per language)
    g = quality_gate(_metrics(0.70, 0.76, cand_uk=0.73))
    assert g["overall"] == "fail"
    failed = {(c["lang"], c["metric"]) for c in g["criteria"] if c["status"] == "fail"}
    assert failed == {("uk", "recall@5"), ("uk", "mrr")}
    assert quality_gate(_metrics(0.70, 0.7499))["overall"] == "fail"
    assert quality_gate(_metrics(0.70, 0.75))["overall"] == "pass"  # boundary


def test_gate_missing_language_is_not_evaluated() -> None:
    m = _metrics(0.7, 0.8)
    m["tuned_hybrid"]["uk"] = {"n": 0}
    assert quality_gate(m)["overall"] == "not_evaluated"
