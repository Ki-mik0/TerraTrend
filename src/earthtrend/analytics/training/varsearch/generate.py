"""Training pairs for M3 VarSearch: query -> variable, UA/EN (PLAN_ANALYTICS 11.4).

No LLM is available offline, so queries come from templates x a hand-written lexicon
(`lexicon.yaml`), with:
* styles: `school` (pupil), `scientist`, `casual` (search-box keywords), `phenomenon`
  (whole questions about a phenomenon, "чи стає сухіше");
* synonyms per register, UA nominative/genitive forms;
* noise: typos (delete / swap / double / neighbour key), lowercase, wrong keyboard layout
  (Ukrainian typed on the Latin layout);
* hard negatives: a `confusable_with` variable of the positive (air vs surface temperature).

These are *training* and *dev* queries. They are never the human test (11.4): the human set
is loaded only from `human_test/human_test.csv` and checked for overlap with these pairs.

Split rule (dev = generalization check on the synthetic distribution): a pair is `dev` when
its template id or its term is in the held-out hash bucket; the variable's own catalog names
are always `train`.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from earthtrend.analytics.ml.varsearch_catalog import LANGS, Lang, VariableCatalog
from earthtrend.analytics.ml.varsearch_lexical import words

GENERATOR_VERSION = "varsearch-pairs-v1"
LEXICON_PATH = Path(__file__).with_name("lexicon.yaml")

Style = Literal["school", "scientist", "casual", "phenomenon", "name"]
Split = Literal["train", "dev"]


@dataclass(frozen=True)
class Template:
    id: str
    lang: Lang
    style: Style
    text: str  # "{t}" nominative term, "{g}" genitive term, "{p}" place, "{y}" period
    register: Literal["plain", "sci", "any"] = "any"

    @property
    def needs_gen(self) -> bool:
        return "{g}" in self.text


def _t(tid: str, lang: Lang, style: Style, text: str, register: str = "any") -> Template:
    return Template(tid, lang, style, text, register)  # type: ignore[arg-type]


TEMPLATES: tuple[Template, ...] = (
    # ------------------------------------------------------------- en
    _t("en_s01", "en", "school", "{t}", "plain"),
    _t("en_s02", "en", "school", "how has {t} changed", "plain"),
    _t("en_s03", "en", "school", "is {t} going up", "plain"),
    _t("en_s04", "en", "school", "{t} over the years", "plain"),
    _t("en_s05", "en", "school", "why is {t} changing {p}", "plain"),
    _t("en_s06", "en", "school", "show me {t} {p}", "plain"),
    _t("en_s07", "en", "school", "has {t} increased {y}", "plain"),
    _t("en_s08", "en", "school", "{t} {p} {y}", "plain"),
    _t("en_s09", "en", "school", "what happened to {t} {p}", "plain"),
    _t("en_s10", "en", "school", "school project about {t}", "plain"),
    _t("en_c01", "en", "casual", "{t}"),
    _t("en_c02", "en", "casual", "{t} data"),
    _t("en_c03", "en", "casual", "{t} trend"),
    _t("en_c04", "en", "casual", "{t} {p}"),
    _t("en_c05", "en", "casual", "{t} map"),
    _t("en_k01", "en", "scientist", "trend in {t}", "sci"),
    _t("en_k02", "en", "scientist", "long-term trend of {t} {y}", "sci"),
    _t("en_k03", "en", "scientist", "{t} anomaly time series", "sci"),
    _t("en_k04", "en", "scientist", "monthly {t} {p}", "sci"),
    _t("en_k05", "en", "scientist", "{t} climatology and anomalies", "sci"),
    _t("en_k06", "en", "scientist", "interannual variability of {t}", "sci"),
    _t("en_k07", "en", "scientist", "satellite record of {t} {y}", "sci"),
    _t("en_k08", "en", "scientist", "regional mean {t} {p}", "sci"),
    _t("en_k09", "en", "scientist", "detecting a trend in {t}", "sci"),
    # ------------------------------------------------------------- uk
    _t("uk_s01", "uk", "school", "{t}", "plain"),
    _t("uk_s02", "uk", "school", "{t} {p}", "plain"),
    _t("uk_s03", "uk", "school", "{t} за останні роки", "plain"),
    _t("uk_s04", "uk", "school", "як змінюється {t}", "plain"),
    _t("uk_s05", "uk", "school", "{t} {p} {y}", "plain"),
    _t("uk_s06", "uk", "school", "що відбувається з {t}", "plain"),
    _t("uk_s07", "uk", "school", "зміни {g} {p}", "plain"),
    _t("uk_s08", "uk", "school", "проєкт для школи про {t}", "plain"),
    _t("uk_s09", "uk", "school", "чому змінюється {t}", "plain"),
    _t("uk_s10", "uk", "school", "графік {g} {y}", "plain"),
    _t("uk_c01", "uk", "casual", "{t}"),
    _t("uk_c02", "uk", "casual", "{t} дані"),
    _t("uk_c03", "uk", "casual", "{t} тренд"),
    _t("uk_c04", "uk", "casual", "{t} {p}"),
    _t("uk_c05", "uk", "casual", "карта {g}"),
    _t("uk_k01", "uk", "scientist", "тренд {g}", "sci"),
    _t("uk_k02", "uk", "scientist", "довгостроковий тренд {g} {y}", "sci"),
    _t("uk_k03", "uk", "scientist", "часовий ряд аномалій {g}", "sci"),
    _t("uk_k04", "uk", "scientist", "середньомісячні значення {g} {p}", "sci"),
    _t("uk_k05", "uk", "scientist", "кліматологія та аномалії {g}", "sci"),
    _t("uk_k06", "uk", "scientist", "міжрічна мінливість {g}", "sci"),
    _t("uk_k07", "uk", "scientist", "супутникові дані {g} {y}", "sci"),
    _t("uk_k08", "uk", "scientist", "{t}: регіональне середнє {p}", "sci"),
    _t("uk_k09", "uk", "scientist", "виявлення тренду {g}", "sci"),
)

PLACES: dict[Lang, tuple[str, ...]] = {
    "en": (
        "in Ukraine",
        "in Kyiv",
        "in the Carpathians",
        "in Europe",
        "in the Arctic",
        "over India",
        "in California",
        "in the Sahara",
        "near Odesa",
        "in the Amazon",
        "in my region",
        "in Lviv",
    ),
    "uk": (
        "в Україні",
        "у Києві",
        "в Карпатах",
        "на Поліссі",
        "в Одесі",
        "у Європі",
        "в Арктиці",
        "на півдні України",
        "у Сахарі",
        "в Індії",
        "у моєму регіоні",
        "у Львові",
        "на Закарпатті",
    ),
}
PERIODS: dict[Lang, tuple[str, ...]] = {
    "en": (
        "since 2000",
        "over the last 20 years",
        "2003-2023",
        "in summer",
        "in winter",
        "since the 1980s",
        "last decade",
    ),
    "uk": (
        "з 2000 року",
        "за останні 20 років",
        "2003-2023",
        "влітку",
        "взимку",
        "з 1980-х",
        "за останнє десятиліття",
    ),
}

# Keyboard rows for neighbour-key typos.
_ROWS: dict[Lang, tuple[str, ...]] = {
    "en": ("qwertyuiop", "asdfghjkl", "zxcvbnm"),
    "uk": ("йцукенгшщзхї", "фівапролджє", "ячсмитьбю"),
}
# Ukrainian letters -> the Latin key at the same position (ЙЦУКЕН -> QWERTY).
_UA_TO_LATIN = str.maketrans("йцукенгшщзхїфівапролджєячсмитьбю", "qwertyuiop[]asdfghjkl;'zxcvbnm,.")


@dataclass
class Pair:
    query: str
    lang: Lang
    style: Style
    positive: str
    relevant: list[str]
    hard_negative: str
    template_id: str
    term: str
    noise: list[str] = field(default_factory=list)
    split: Split = "train"
    source: str = "template"

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Lexicon:
    version: str
    terms: dict[str, dict[str, dict[str, list[str]]]]
    phenomena: dict[str, list[dict[str, Any]]]


def load_lexicon(path: str | Path = LEXICON_PATH) -> Lexicon:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Lexicon(raw["version"], raw["terms"], raw["phenomena"])


def check_lexicon(lex: Lexicon, catalog: VariableCatalog) -> list[str]:
    """Problems between lexicon and catalog (empty list = consistent)."""
    ids = set(catalog.ids)
    problems = [f"lexicon term for unknown variable {k}" for k in lex.terms if k not in ids]
    for vid in catalog.ids:
        entry = lex.terms.get(vid)
        if entry is None:
            problems.append(f"no lexicon terms for {vid}")
            continue
        for lang in LANGS:
            for reg in ("plain", "sci"):
                if not entry.get(lang, {}).get(reg):
                    problems.append(f"{vid}: empty {lang}.{reg}")
    for plang, items in lex.phenomena.items():
        for it in items:
            bad = [r for r in it["relevant"] if r not in ids]
            if bad:
                problems.append(f"phenomenon {plang} {it['text']!r}: unknown {bad}")
    return problems


def _bucket(key: str, salt: str) -> float:
    h = hashlib.sha256(f"{salt}:{key}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def _split_terms(term: str) -> tuple[str, str | None]:
    nom, _, gen = term.partition("|")
    return nom.strip(), (gen.strip() or None)


# ---------------------------------------------------------------- noise


def typo(text: str, lang: Lang, rng: random.Random) -> str:
    """One random edit inside a word of >= 4 letters (left unchanged if there is none)."""
    tokens = text.split(" ")
    cand = [i for i, w in enumerate(tokens) if sum(ch.isalpha() for ch in w) >= 4]
    if not cand:
        return text
    i = rng.choice(cand)
    w = tokens[i]
    pos = rng.randrange(1, len(w) - 1)
    op = rng.choice(("delete", "swap", "double", "neighbour"))
    if op == "delete":
        w = w[:pos] + w[pos + 1 :]
    elif op == "swap":
        w = w[: pos - 1] + w[pos] + w[pos - 1] + w[pos + 1 :]
    elif op == "double":
        w = w[:pos] + w[pos] + w[pos:]
    else:
        ch = w[pos].lower()
        for row in _ROWS[lang]:
            k = row.find(ch)
            if k >= 0:
                nb = [row[j] for j in (k - 1, k + 1) if 0 <= j < len(row)]
                w = w[:pos] + rng.choice(nb) + w[pos + 1 :]
                break
    tokens[i] = w
    return " ".join(tokens)


def wrong_layout(text: str) -> str:
    """Ukrainian text typed with the Latin layout on ("ntvgthfnehf" for "температура")."""
    return text.lower().translate(_UA_TO_LATIN)


def add_noise(text: str, lang: Lang, rng: random.Random) -> tuple[str, list[str]]:
    applied: list[str] = []
    r = rng.random()
    if r < 0.22:
        text, applied = typo(text, lang, rng), ["typo"]
    elif r < 0.30:
        text = typo(typo(text, lang, rng), lang, rng)
        applied = ["typo", "typo"]
    if rng.random() < 0.5:
        text = text.lower()
        applied.append("lower")
    if lang == "uk" and rng.random() < 0.03:
        text = wrong_layout(text)
        applied.append("layout")
    return text, applied


# ---------------------------------------------------------------- generation


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int = 13
    per_variable_lang: int = 36  # template pairs per variable and language
    phenomenon_variants: int = 4  # noisy copies of each phenomenon question
    dev_template_fraction: float = 0.2
    dev_term_fraction: float = 0.15
    negatives_from_confusable: float = 0.85


def _relevant(catalog: VariableCatalog, positive: str, query: str) -> list[str]:
    """Same-concept variables are all correct, unless the query names the product."""
    group = catalog.same_concept(positive)
    if len(group) == 1:
        return group
    docs = catalog.by_id()
    qwords = {w for w in words(query) if len(w) >= 3}

    def product(vid: str) -> set[str]:
        return {w for w in words(docs[vid].source) if len(w) >= 3 and not w.isdigit()}

    own = product(positive) - set().union(*(product(o) for o in group if o != positive))
    return [positive] if qwords & own else group


def _hard_negative(
    catalog: VariableCatalog, relevant: list[str], rng: random.Random, p_conf: float
) -> str:
    docs = catalog.by_id()
    conf = [c for r in relevant for c in docs[r].confusable_with if c not in relevant]
    if conf and rng.random() < p_conf:
        return rng.choice(conf)
    others = [v for v in catalog.ids if v not in relevant]
    return rng.choice(others)


def generate_pairs(
    catalog: VariableCatalog, lexicon: Lexicon, config: GeneratorConfig | None = None
) -> list[Pair]:
    cfg = config or GeneratorConfig()
    rng = random.Random(cfg.seed)
    salt = f"{GENERATOR_VERSION}:{cfg.seed}"
    dev_tpl = {t.id for t in TEMPLATES if _bucket(t.id, salt) < cfg.dev_template_fraction}
    pairs: list[Pair] = []
    seen: set[tuple[str, str]] = set()

    def emit(p: Pair) -> None:
        key = (p.query.lower(), p.positive)
        if p.query.strip() and key not in seen:
            seen.add(key)
            pairs.append(p)

    for doc in catalog.variables:
        for lang in LANGS:
            # catalog names: always train, clean
            name = doc.names.get(lang)
            emit(
                Pair(
                    name,
                    lang,
                    "name",
                    doc.id,
                    _relevant(catalog, doc.id, name),
                    _hard_negative(catalog, [doc.id], rng, cfg.negatives_from_confusable),
                    template_id="name",
                    term=name,
                    source="catalog_name",
                )
            )
            entry = lexicon.terms[doc.id][lang]
            combos: list[tuple[Template, str, str | None, str]] = []
            for reg in ("plain", "sci"):
                for raw in entry[reg]:
                    nom, gen = _split_terms(raw)
                    for tpl in TEMPLATES:
                        if tpl.lang != lang or tpl.register not in (reg, "any"):
                            continue
                        if tpl.needs_gen and gen is None:
                            continue
                        combos.append((tpl, nom, gen, raw))
            rng.shuffle(combos)
            for tpl, nom, gen, raw in combos[: cfg.per_variable_lang]:
                text = tpl.text.format(
                    t=nom, g=gen or nom, p=rng.choice(PLACES[lang]), y=rng.choice(PERIODS[lang])
                )
                text = " ".join(text.split())
                query, noise = add_noise(text, lang, rng)
                relevant = _relevant(catalog, doc.id, text)
                is_dev = tpl.id in dev_tpl or _bucket(raw, salt) < cfg.dev_term_fraction
                emit(
                    Pair(
                        query,
                        lang,
                        tpl.style,
                        doc.id,
                        relevant,
                        _hard_negative(catalog, relevant, rng, cfg.negatives_from_confusable),
                        template_id=tpl.id,
                        term=nom,
                        noise=noise,
                        split="dev" if is_dev else "train",
                    )
                )

    for lang in LANGS:
        for k, item in enumerate(lexicon.phenomena[lang]):
            relevant = list(item["relevant"])
            split: Split = "dev" if _bucket(item["text"], salt) < 0.25 else "train"
            for v in range(cfg.phenomenon_variants):
                text = item["text"]
                query, noise = (text, []) if v == 0 else add_noise(text, lang, rng)
                emit(
                    Pair(
                        query,
                        lang,
                        "phenomenon",
                        relevant[v % len(relevant)],
                        relevant,
                        _hard_negative(catalog, relevant, rng, cfg.negatives_from_confusable),
                        template_id=f"phen_{lang}_{k:02d}",
                        term=text,
                        noise=noise,
                        split=split,
                        source="phenomenon",
                    )
                )
    return pairs
