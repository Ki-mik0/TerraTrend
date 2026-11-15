"""One file per export format, all built from the same `Report`. Numbers are copied from the stored case."""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import date

from jinja2 import Environment
from scipy.io import netcdf_file

from earthtrend.api.domain.cases.model import Case
from earthtrend.api.infrastructure.exports.charts import card_png, months_chart, report_pdf, series_chart, verdict_colour
from earthtrend.api.infrastructure.exports.report import Names, Report, build_report

MEDIA = {
    "csv": "text/csv; charset=utf-8",
    "geojson": "application/geo+json",
    "ipynb": "application/x-ipynb+json",
    "html": "text/html; charset=utf-8",
    "png": "image/png",
    "pdf": "application/pdf",
    "zip": "application/zip",
    "nc": "application/x-netcdf",
    "svg": "image/svg+xml",
    "citation": "text/plain; charset=utf-8",
}
EXTENSION = {"citation": "txt"}


def filename(report: Report, fmt: str) -> str:
    """A readable file name: terratrend-<variable>-<region>-<period>.<ext>, ASCII only."""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{report.variable_id}-{report.region_id}-{report.period}".lower()).strip("-")
    return f"terratrend-{slug}.{EXTENSION.get(fmt, fmt)}"


def render(case: Case, fmt: str, names: Names | None = None, language: str | None = None) -> bytes:
    report = build_report(case, names or Names(variable=case.spec.variable_id, region=case.spec.region_id), language)
    builders = {
        "csv": _csv,
        "geojson": _geojson,
        "ipynb": _notebook,
        "html": _html,
        "png": card_png,
        "pdf": lambda item: report_pdf(item, citation(item)),
        "svg": lambda item: series_chart(item, "svg"),
        "nc": _netcdf,
        "zip": _zip,
    }
    builder = builders.get(fmt)
    return builder(report) if builder else citation(report).encode("utf-8")


def citation(report: Report) -> str:
    year = report.generated_at[:4]
    lines = [
        f"TerraTrend Detective ({year}). {report.title}, {report.period}. "
        + report.t("Справа", "Case")
        + f" {report.case_id}. "
        + report.t("Вирок", "Verdict")
        + f": {report.verdict_label}.",
        f"{report.t('Дані', 'Data')}: {report.source}." + (f" DOI: https://doi.org/{report.doi}" if report.doi else ""),
        f"{report.t('Версії', 'Versions')}: " + ", ".join(f"{key} {value}" for key, value in report.versions.items() if value),
        "",
        "@misc{terratrend_" + re.sub(r"[^a-z0-9]+", "_", report.case_id.lower()) + ",",
        f"  title  = {{{{TerraTrend: {report.title}, {report.period}}}}},",
        f"  author = {{{{TerraTrend Detective}}}},",
        f"  year   = {{{year}}},",
        f"  note   = {{{report.verdict_label}; {report.source}}}" + (f",\n  doi    = {{{report.doi}}}" if report.doi else ""),
        "}",
    ]
    return "\n".join(lines) + "\n"


def _csv(report: Report) -> bytes:
    """Data a spreadsheet opens directly (UTF-8 with BOM for Excel): the monthly series, or the month slopes."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if report.series_dates:
        writer.writerow(["date", "value", "units", "variable", "region", "source"])
        for when, value in zip(report.series_dates, report.series_values, strict=False):
            writer.writerow([when.isoformat(), "" if value is None else value, report.units, report.variable, report.region, report.source])
    else:
        writer.writerow(["month", "change_per_decade", "units", "variable", "region", "verdict", "source"])
        for month, slope in report.months:
            writer.writerow([month, slope, report.units, report.variable, report.region, report.verdict_code, report.source])
        # The whole-year trend closes the table, so the headline number is in the file too.
        writer.writerow(["year", report.slope, report.units, report.variable, report.region, report.verdict_code, report.source])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def _properties(report: Report) -> dict:
    return {
        "case_id": report.case_id,
        "variable_id": report.variable_id,
        "variable": report.variable,
        "region_id": report.region_id,
        "region": report.region,
        "period": report.period,
        "season": report.season,
        "verdict": report.verdict_code,
        "verdict_label": report.verdict_label,
        "summary": report.sentence,
        "change_per_decade": report.slope,
        "units": report.units,
        "direction": report.direction,
        "source": report.source,
        **report.evidence,
        "fill": verdict_colour(report),
    }


def _geojson(report: Report) -> bytes:
    geometry = None
    if report.bbox is not None:
        west, south, east, north = report.bbox
        geometry = {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]]}
    payload = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geometry, "properties": _properties(report)}]}
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _notebook(report: Report) -> bytes:
    data = {
        "date": [when.isoformat() for when in report.series_dates],
        "value": report.series_values,
    }
    checks = "\n".join(f"- {'✅' if item.status == 'ok' else '⚠️' if item.status == 'warn' else '❌'} **{item.title}:** {item.text}" for item in report.checks)
    cells = [
        _markdown(
            f"# {report.title}\n\n**{report.period} · {report.season}**\n\n"
            f"> {report.sentence}\n\n**{report.t('Вирок', 'Verdict')}: {report.verdict_label}.** {report.verdict_meaning}\n\n{checks}\n\n"
            f"*{report.t('Дані', 'Data')}: {report.source}. {report.source_note}*"
        ),
        _markdown(report.t("## Дані справи\nРяд нижче — ті самі значення, з яких порахована справа.", "## Case data\nThe series below holds the same values the case was computed from.")),
        _code(
            "import pandas as pd\nimport matplotlib.pyplot as plt\n\n"
            f"data = pd.DataFrame({json.dumps(data, ensure_ascii=False)})\n"
            "data['date'] = pd.to_datetime(data['date'])\n"
            "data = data.set_index('date')\n"
            "data.head()"
        ),
        _code(
            "yearly = data['value'].resample('YS').mean()\n"
            "ax = data['value'].plot(alpha=0.25, figsize=(10, 4), label='monthly')\n"
            "yearly.plot(ax=ax, linewidth=2.5, marker='o', label='yearly mean')\n"
            f"ax.set_title({json.dumps(report.title, ensure_ascii=False)})\n"
            f"ax.set_ylabel({json.dumps(report.units or 'value', ensure_ascii=False)})\n"
            "ax.legend(); plt.show()"
        ),
        _markdown(
            report.t(
                f"## Числа протоколу\nЗміна за 10 років: **{report.slope}** {report.units}\n\n```json\n{json.dumps(report.evidence, ensure_ascii=False, indent=2)}\n```",
                f"## Protocol numbers\nChange per decade: **{report.slope}** {report.units}\n\n```json\n{json.dumps(report.evidence, ensure_ascii=False, indent=2)}\n```",
            )
        ),
        _markdown(report.t("## Як цитувати\n```\n", "## How to cite\n```\n") + citation(report) + "```"),
    ]
    if not report.series_dates:
        cells[2] = _code(
            "import pandas as pd\n\n"
            f"months = pd.DataFrame({json.dumps({'month': [m for m, _ in report.months], 'change_per_decade': [s for _, s in report.months]})})\n"
            "months.plot.bar(x='month', y='change_per_decade', legend=False)"
        )
        cells[3] = _markdown(report.t("Для цієї справи збережено лише підсумки по місяцях.", "Only monthly summaries are stored for this case."))
    payload = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}, "language_info": {"name": "python"}},
        "cells": cells,
    }
    return json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")


def _markdown(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def _code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": text.splitlines(keepends=True)}


def _inline_svg(data: bytes) -> str:
    text = data.decode("utf-8")
    return text[text.index("<svg") :]


_HTML = Environment(autoescape=True).from_string(
    """<!DOCTYPE html>
<html lang="{{ r.language }}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TerraTrend — {{ r.title }}</title>
<style>
  :root { --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --brand1:#2563eb; --brand2:#059669; --verdict:{{ colour }}; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:Inter, "Segoe UI", system-ui, -apple-system, sans-serif; color:var(--ink); background:#f8fafc; line-height:1.55; }
  .page { max-width:920px; margin:32px auto; background:white; border-radius:20px; box-shadow:0 10px 40px rgba(15,23,42,.08); overflow:hidden; }
  .bar { height:6px; background:linear-gradient(90deg,var(--brand1),var(--brand2)); }
  header, section { padding:28px 40px; }
  section { border-top:1px solid var(--line); }
  .eyebrow { font-size:12px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); }
  h1 { font-size:32px; margin:8px 0 4px; letter-spacing:-.02em; }
  h2 { font-size:18px; margin:0 0 14px; }
  .meta { color:var(--muted); }
  .verdict { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:16px; margin-top:22px; padding:18px 22px; border-radius:16px;
             background:color-mix(in srgb, var(--verdict) 10%, white); border:1px solid color-mix(in srgb, var(--verdict) 35%, white); }
  .verdict b { color:var(--verdict); font-size:22px; }
  .slope { color:var(--verdict); font-size:30px; font-weight:800; white-space:nowrap; }
  .slope small { font-size:14px; font-weight:500; color:var(--muted); }
  .lead { font-size:19px; margin:0 0 8px; }
  ul.checks { list-style:none; padding:0; margin:0; display:grid; gap:10px; }
  ul.checks li { display:flex; gap:12px; align-items:flex-start; padding:12px 14px; border:1px solid var(--line); border-radius:12px; }
  .mark { width:24px; height:24px; border-radius:50%; flex:none; display:grid; place-items:center; color:white; font-weight:800; font-size:14px; }
  .ok { background:#059669; } .warn { background:#d97706; } .bad { background:#dc2626; }
  figure { margin:0; } figure svg { width:100%; height:auto; }
  table { width:100%; border-collapse:collapse; } td { padding:9px 0; border-bottom:1px solid var(--line); } td:last-child { text-align:right; font-weight:700; }
  .source { display:inline-block; padding:3px 10px; border-radius:999px; background:#ecfdf5; color:#047857; font-weight:600; font-size:13px; }
  pre { white-space:pre-wrap; background:#f1f5f9; padding:14px; border-radius:12px; font-size:12.5px; }
  footer { padding:18px 40px 28px; color:var(--muted); font-size:12px; }
  @media print { body { background:white; } .page { box-shadow:none; margin:0; border-radius:0; } section { break-inside:avoid; } }
  @media (max-width:640px) { header, section, footer { padding:22px; } h1 { font-size:25px; } }
</style>
</head>
<body>
<main class="page">
  <div class="bar"></div>
  <header>
    <div class="eyebrow">{{ r.t("Звіт розслідування · TerraTrend Detective", "Investigation report · TerraTrend Detective") }}</div>
    <h1>{{ r.variable }}</h1>
    <div class="meta">{{ r.region }} · {{ r.period }} · {{ r.season }}</div>
    <div class="verdict">
      <div>{{ r.t("Вирок", "Verdict") }}: <b>{{ r.verdict_label }}</b><div class="meta">{{ r.verdict_meaning }}</div></div>
      <div class="slope">{{ slope }} <small>{{ r.t("за 10 років", "per decade") }}</small></div>
    </div>
  </header>
  <section>
    <h2>{{ r.t("Що це означає", "What this means") }}</h2>
    <p class="lead">{{ r.sentence }}</p>
  </section>
  <section>
    <h2>{{ r.t("Що показали перевірки", "What the checks showed") }}</h2>
    <ul class="checks">
      {% for c in r.checks %}<li><span class="mark {{ c.status }}">{{ {"ok": "✓", "warn": "!", "bad": "✗"}[c.status] }}</span><span><b>{{ c.title }}.</b> {{ c.text }}</span></li>{% endfor %}
    </ul>
  </section>
  <section><figure>{{ chart | safe }}</figure></section>
  {% if months %}<section><figure>{{ months | safe }}</figure></section>{% endif %}
  <section>
    <h2>{{ r.t("Числа протоколу доказів", "Evidence protocol numbers") }}</h2>
    <table>
      <tr><td>{{ r.t("Свідки (незалежні джерела)", "Witnesses (independent sources)") }}</td><td>{{ r.evidence.witnesses_confirmed }} / {{ r.evidence.witnesses_total }}</td></tr>
      <tr><td>{{ r.t("Стійкість", "Robustness") }}</td><td>{{ (r.evidence.triangle_same_sign_share * 100) | round | int }}%</td></tr>
      <tr><td>{{ r.t("Алібі: до / після поправки", "Alibi: before / after correction") }}</td><td>{{ "%.3f" | format(r.evidence.alibi_b_raw) }} / {{ "%.3f" | format(r.evidence.alibi_b_adjusted) }}</td></tr>
      <tr><td>{{ r.t("Пропущені місяці", "Missing months") }}</td><td>{{ ((r.evidence.gap_fraction or 0) * 100) | round | int }}%</td></tr>
      <tr><td>n_eff</td><td>{{ "%.1f" | format(r.evidence.n_eff or 0) }}</td></tr>
    </table>
  </section>
  <section>
    <h2>{{ r.t("Дані і цитування", "Data and citation") }}</h2>
    <p><span class="source">{{ r.source }}</span> {{ r.source_note }}</p>
    <pre>{{ cite }}</pre>
  </section>
  <footer>{{ r.t("Справа", "Case") }} {{ r.case_id }} · {{ r.generated_at }} · {{ r.t("Згенеровано TerraTrend Detective", "Generated by TerraTrend Detective") }}</footer>
</main>
</body>
</html>
"""
)


def _slope_label(report: Report) -> str:
    if report.slope is None:
        return "—"
    sign = "+" if report.slope > 0 else "−" if report.slope < 0 else ""
    return f"{sign}{abs(report.slope):.2f} {report.units}".strip()


def _html(report: Report) -> bytes:
    return _HTML.render(
        r=report,
        colour=verdict_colour(report),
        slope=_slope_label(report),
        chart=_inline_svg(series_chart(report, "svg")),
        months=_inline_svg(months_chart(report, "svg")) if report.months and report.annual else "",
        cite=citation(report),
    ).encode("utf-8")


def _utf8(text: str) -> bytes:
    """NetCDF-3 text attributes are byte strings; UTF-8 keeps Cyrillic names readable in xarray and Panoply."""
    return text.encode("utf-8")


def _netcdf(report: Report) -> bytes:
    """NetCDF-3 with the monthly series (CF time axis) and the case summary as global attributes."""
    buffer = io.BytesIO()
    nc = netcdf_file(buffer, "w")
    nc.title = _utf8(f"TerraTrend: {report.title}, {report.period}")
    nc.summary = _utf8(report.sentence)
    nc.verdict = report.verdict_code
    nc.source = _utf8(report.source)
    nc.case_id = report.case_id
    nc.Conventions = "CF-1.8"
    if report.series_dates:
        nc.createDimension("time", len(report.series_dates))
        time = nc.createVariable("time", "f8", ("time",))
        time.units = "days since 1970-01-01"
        time.calendar = "standard"
        time[:] = [(when - date(1970, 1, 1)).days for when in report.series_dates]
        value = nc.createVariable("value", "f8", ("time",))
        value.long_name = _utf8(report.variable)
        value.units = _utf8(report.units)
        value._FillValue = -9999.0
        value[:] = [-9999.0 if item is None else item for item in report.series_values]
    nc.createDimension("month", 12)
    month = nc.createVariable("month", "i4", ("month",))
    month[:] = list(range(1, 13))
    slopes = nc.createVariable("change_per_decade", "f8", ("month",))
    slopes.units = _utf8(f"{report.units} per decade".strip())
    by_month = dict(report.months)
    slopes[:] = [by_month.get(index, -9999.0) for index in range(1, 13)]
    nc.flush()
    data = buffer.getvalue()
    nc.close()
    return data


def _zip(report: Report) -> bytes:
    """Everything in one archive, with a README that says what each file is."""
    readme = report.t(
        f"""# {report.title}, {report.period}

{report.sentence}

Вирок: {report.verdict_label}. {report.verdict_meaning}

Файли:
- report.html — звіт для браузера і друку
- report.pdf — той самий звіт у PDF
- card.png — картка для соцмереж
- chart.svg — графік (векторний)
- data.csv — дані справи для таблиць
- case.geojson — регіон із результатом для ГІС
- notebook.ipynb — Jupyter-ноутбук з даними і графіками
- data.nc — NetCDF для наукових інструментів
- citation.txt — як цитувати
""",
        f"""# {report.title}, {report.period}

{report.sentence}

Verdict: {report.verdict_label}. {report.verdict_meaning}

Files:
- report.html — report for the browser and print
- report.pdf — the same report as PDF
- card.png — share card
- chart.svg — chart (vector)
- data.csv — case data for spreadsheets
- case.geojson — region with the result for GIS
- notebook.ipynb — Jupyter notebook with data and charts
- data.nc — NetCDF for science tools
- citation.txt — how to cite
""",
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", readme)
        archive.writestr("report.html", _html(report))
        archive.writestr("report.pdf", report_pdf(report, citation(report)))
        archive.writestr("card.png", card_png(report))
        archive.writestr("chart.svg", series_chart(report, "svg"))
        archive.writestr("data.csv", _csv(report))
        archive.writestr("case.geojson", _geojson(report))
        archive.writestr("notebook.ipynb", _notebook(report))
        archive.writestr("data.nc", _netcdf(report))
        archive.writestr("citation.txt", citation(report))
    return buffer.getvalue()
