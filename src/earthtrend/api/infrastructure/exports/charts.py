"""Charts and print layouts for exports, drawn with matplotlib (Agg, no display).

The bundled DejaVu Sans font covers Cyrillic, so reports read the same on Windows and in Docker.
The trend line uses the slope from the analytics; nothing is refitted here.
"""

from __future__ import annotations

import io
import textwrap
from datetime import date

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from earthtrend.api.infrastructure.exports.report import Report  # noqa: E402

INK = "#0f172a"
MUTED = "#64748b"
GRID = "#e2e8f0"
BRAND_FROM = "#2563eb"
BRAND_TO = "#059669"
WARM = "#dc4a2b"
COOL = "#2563eb"
STATUS = {"ok": ("#059669", "✓"), "warn": ("#d97706", "!"), "bad": ("#dc2626", "✗")}

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.edgecolor": GRID,
        "axes.labelcolor": MUTED,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "svg.fonttype": "none",
    }
)


def verdict_colour(report: Report) -> str:
    if report.verdict_code in {"proven", "strong"}:
        return COOL if report.direction == "decreasing" else WARM
    return {"likely": "#ca8a04", "suspicious": "#ea580c"}.get(report.verdict_code, "#64748b")


def _save(figure: Figure, fmt: str, dpi: int = 150, tight: bool = True) -> bytes:
    buffer = io.BytesIO()
    figure.savefig(buffer, format=fmt, dpi=dpi, bbox_inches="tight" if tight else None, facecolor=figure.get_facecolor())
    plt.close(figure)
    return buffer.getvalue()


def _draw_series(axis, report: Report) -> None:
    """Monthly values (faint), yearly means (bold) and the analytics trend line through their middle."""
    if report.series_dates:
        pairs = [(when, value) for when, value in zip(report.series_dates, report.series_values, strict=False) if value is not None]
        axis.plot([when for when, _ in pairs], [value for _, value in pairs], color=BRAND_FROM, alpha=0.18, linewidth=0.8)
    if report.annual:
        years = [year for year, _ in report.annual]
        values = [value for _, value in report.annual]
        axis.plot([date(year, 7, 1) for year in years], values, color=BRAND_FROM, linewidth=2.2, marker="o", markersize=3.5, label=report.t("середнє за рік", "yearly mean"))
        if report.slope is not None:
            middle = (years[0] + years[-1]) / 2
            centre = sum(values) / len(values)
            ends = [years[0], years[-1]]
            axis.plot(
                [date(year, 7, 1) for year in ends],
                [centre + report.slope / 10 * (year - middle) for year in ends],
                color=verdict_colour(report),
                linewidth=2.6,
                linestyle="--",
                label=report.t("тренд", "trend"),
            )
        axis.legend(frameon=False, loc="upper left", fontsize=9)
    axis.grid(axis="y", color=GRID, linewidth=0.8)
    axis.set_ylabel(report.units or report.t("значення", "value"))


def _draw_months(axis, report: Report) -> None:
    labels_uk = ["січ", "лют", "бер", "кві", "тра", "чер", "лип", "сер", "вер", "жов", "лис", "гру"]
    labels_en = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    labels = labels_en if report.language == "en" else labels_uk
    months = [month for month, _ in report.months]
    slopes = [slope for _, slope in report.months]
    axis.bar([labels[month - 1] for month in months], slopes, color=[WARM if value >= 0 else COOL for value in slopes], width=0.65)
    axis.axhline(0, color=MUTED, linewidth=0.8)
    axis.grid(axis="y", color=GRID, linewidth=0.8)
    axis.set_ylabel(f"{report.units} / 10 {report.t('р.', 'y')}".strip(" /"))


def series_chart(report: Report, fmt: str = "svg") -> bytes:
    figure, axis = plt.subplots(figsize=(9, 3.6))
    if report.annual:
        _draw_series(axis, report)
        axis.set_title(report.t("Як змінювалась величина", "How the quantity changed"), loc="left", color=INK, fontsize=12, fontweight="bold")
    else:
        _draw_months(axis, report)
        axis.set_title(report.t("Зміна кожного місяця за 10 років", "Change of each month per decade"), loc="left", color=INK, fontsize=12, fontweight="bold")
    return _save(figure, fmt)


def months_chart(report: Report, fmt: str = "svg") -> bytes:
    figure, axis = plt.subplots(figsize=(9, 3.2))
    _draw_months(axis, report)
    axis.set_title(report.t("Який місяць змінюється найбільше", "Which month changes most"), loc="left", color=INK, fontsize=12, fontweight="bold")
    return _save(figure, fmt)


def _slope_text(report: Report) -> str:
    if report.slope is None:
        return "—"
    sign = "+" if report.slope > 0 else "−" if report.slope < 0 else ""
    return f"{sign}{abs(report.slope):.2f} {report.units}".strip()


def card_png(report: Report) -> bytes:
    """A 1200×630 share card: title, verdict, the number and a sparkline."""
    figure = plt.figure(figsize=(12, 6.3), dpi=100)
    figure.patch.set_facecolor("#0b1020")
    canvas = figure.add_axes((0, 0, 1, 1))
    canvas.set_axis_off()
    canvas.set_xlim(0, 1)
    canvas.set_ylim(0, 1)
    gradient = [[index / 255 for index in range(256)]]
    canvas.imshow(gradient, extent=(0, 1, 0.985, 1), aspect="auto", cmap=matplotlib.colors.LinearSegmentedColormap.from_list("brand", [BRAND_FROM, BRAND_TO]))
    canvas.text(0.05, 0.88, "TerraTrend Detective", color="#94a3b8", fontsize=16, fontweight="bold")
    canvas.text(0.05, 0.76, textwrap.shorten(report.variable, 40), color="white", fontsize=34, fontweight="bold")
    canvas.text(0.05, 0.67, f"{report.region} · {report.period}", color="#cbd5e1", fontsize=20)
    colour = verdict_colour(report)
    canvas.add_patch(FancyBboxPatch((0.05, 0.50), 0.30, 0.09, boxstyle="round,pad=0.01,rounding_size=0.04", facecolor=colour, edgecolor="none", alpha=0.95))
    canvas.text(0.065, 0.535, report.verdict_label, color="white", fontsize=22, fontweight="bold", va="center")
    canvas.text(0.05, 0.32, _slope_text(report), color=colour, fontsize=54, fontweight="bold")
    canvas.text(0.05, 0.25, report.t("за 10 років", "per decade"), color="#94a3b8", fontsize=18)
    canvas.text(0.05, 0.08, "\n".join(textwrap.wrap(report.sentence, 70)[:2]), color="#cbd5e1", fontsize=14)
    canvas.text(0.95, 0.88, report.source, color="#fbbf24" if report.versions.get("datasets", "").startswith("demo") else "#94a3b8", fontsize=14, fontweight="bold", ha="right")
    if report.annual:
        spark = figure.add_axes((0.52, 0.30, 0.43, 0.38))
        spark.set_facecolor("#0b1020")
        spark.plot([year for year, _ in report.annual], [value for _, value in report.annual], color=BRAND_TO, linewidth=3)
        spark.fill_between([year for year, _ in report.annual], [value for _, value in report.annual], min(value for _, value in report.annual), color=BRAND_TO, alpha=0.15)
        spark.set_axis_off()
    return _save(figure, "png", dpi=100, tight=False)  # exactly 1200×630, the size social networks expect


def _wrap(text: str, width: int) -> str:
    """Wrap each line on its own, so line breaks in the text (a BibTeX entry) survive."""
    return "\n".join(part for line in text.splitlines() for part in (textwrap.wrap(line, width) or [""]))


def report_pdf(report: Report, citation: str) -> bytes:
    """Two A4 pages: the answer with its evidence and chart, then numbers, data source and citation."""
    buffer = io.BytesIO()
    with PdfPages(buffer, metadata={"Title": f"TerraTrend — {report.title}", "Author": "TerraTrend Detective", "Subject": report.sentence}) as pdf:
        page = plt.figure(figsize=(8.27, 11.69))
        page.patch.set_facecolor("white")
        canvas = page.add_axes((0, 0, 1, 1))
        canvas.set_axis_off()
        canvas.set_xlim(0, 1)
        canvas.set_ylim(0, 1)
        gradient = [[index / 255 for index in range(256)]]
        canvas.imshow(gradient, extent=(0, 1, 0.985, 1), aspect="auto", cmap=matplotlib.colors.LinearSegmentedColormap.from_list("brand", [BRAND_FROM, BRAND_TO]))
        canvas.text(0.07, 0.95, report.t("ЗВІТ РОЗСЛІДУВАННЯ · TERRATREND", "INVESTIGATION REPORT · TERRATREND"), color=MUTED, fontsize=9, fontweight="bold")
        canvas.text(0.07, 0.915, _wrap(report.variable, 40), color=INK, fontsize=22, fontweight="bold", va="top")
        canvas.text(0.07, 0.865, f"{report.region} · {report.period} · {report.season}", color=MUTED, fontsize=12)
        colour = verdict_colour(report)
        canvas.add_patch(FancyBboxPatch((0.07, 0.79), 0.86, 0.055, boxstyle="round,pad=0.006,rounding_size=0.015", facecolor=colour, edgecolor="none", alpha=0.12))
        canvas.text(0.09, 0.8175, report.t("Вирок: ", "Verdict: ") + report.verdict_label, color=colour, fontsize=15, fontweight="bold", va="center")
        canvas.text(0.91, 0.8175, f"{_slope_text(report)} / 10 {report.t('р.', 'y')}", color=colour, fontsize=15, fontweight="bold", va="center", ha="right")
        canvas.text(0.07, 0.765, _wrap(report.sentence, 78), color=INK, fontsize=11, va="top")
        canvas.text(0.07, 0.715, _wrap(report.verdict_meaning, 95), color=MUTED, fontsize=9.5, va="top")
        canvas.text(0.07, 0.675, report.t("Що показали перевірки", "What the checks showed"), color=INK, fontsize=12, fontweight="bold")
        top = 0.648
        for check in report.checks:
            tone, mark = STATUS.get(check.status, ("#64748b", "•"))
            canvas.text(0.075, top, mark, color=tone, fontsize=12, fontweight="bold", va="center")
            canvas.text(0.105, top, f"{check.title}: ", color=INK, fontsize=10, fontweight="bold", va="center")
            canvas.text(0.255, top, _wrap(check.text, 70), color=INK, fontsize=10, va="center")
            top -= 0.032
        chart = page.add_axes((0.11, 0.1, 0.82, 0.33))
        if report.annual:
            _draw_series(chart, report)
            chart.set_title(report.t("Як змінювалась величина", "How the quantity changed"), loc="left", color=INK, fontsize=11, fontweight="bold")
        else:
            _draw_months(chart, report)
            chart.set_title(report.t("Зміна кожного місяця за 10 років", "Change of each month per decade"), loc="left", color=INK, fontsize=11, fontweight="bold")
        canvas.text(0.07, 0.035, f"{report.t('Джерело', 'Source')}: {report.source} · {report.t('справа', 'case')} {report.case_id} · {report.generated_at}", color=MUTED, fontsize=8)
        pdf.savefig(page)
        plt.close(page)

        page = plt.figure(figsize=(8.27, 11.69))
        page.patch.set_facecolor("white")
        canvas = page.add_axes((0, 0, 1, 1))
        canvas.set_axis_off()
        canvas.set_xlim(0, 1)
        canvas.set_ylim(0, 1)
        canvas.text(0.07, 0.94, report.t("Числа протоколу доказів", "Evidence protocol numbers"), color=INK, fontsize=14, fontweight="bold")
        rows = [
            (report.t("Зміна за 10 років", "Change per decade"), _slope_text(report)),
            (report.t("Свідки (незалежні джерела)", "Witnesses (independent sources)"), f"{report.evidence.get('witnesses_confirmed', '—')} / {report.evidence.get('witnesses_total', '—')}"),
            (report.t("Стійкість (частка періодів того ж знаку)", "Robustness (share of periods, same sign)"), f"{report.evidence.get('triangle_same_sign_share', 0) * 100:.0f}%"),
            (report.t("Алібі: нахил до поправки", "Alibi: slope before correction"), f"{report.evidence.get('alibi_b_raw', 0):.3f}"),
            (report.t("Алібі: нахил після ENSO/NAO/вулканів", "Alibi: slope after ENSO/NAO/volcanoes"), f"{report.evidence.get('alibi_b_adjusted', 0):.3f}"),
            (report.t("Пропущені місяці", "Missing months"), f"{(report.evidence.get('gap_fraction') or 0) * 100:.0f}%"),
            (report.t("Ефективна кількість точок (n_eff)", "Effective sample size (n_eff)"), f"{report.evidence.get('n_eff') or 0:.1f}"),
        ]
        top = 0.9
        for label, value in rows:
            canvas.text(0.07, top, label, color=MUTED, fontsize=10.5)
            canvas.text(0.93, top, value, color=INK, fontsize=10.5, fontweight="bold", ha="right")
            canvas.plot([0.07, 0.93], [top - 0.012, top - 0.012], color=GRID, linewidth=0.8)
            top -= 0.035
        if report.months:
            chart = page.add_axes((0.11, top - 0.24, 0.82, 0.2))
            _draw_months(chart, report)
            chart.set_title(report.t("Який місяць змінюється найбільше", "Which month changes most"), loc="left", color=INK, fontsize=11, fontweight="bold")
            top -= 0.3
        canvas.text(0.07, top, report.t("Дані", "Data"), color=INK, fontsize=12, fontweight="bold")
        canvas.text(0.07, top - 0.03, _wrap(f"{report.source}. {report.source_note}", 95), color=INK, fontsize=9.5, va="top")
        canvas.text(0.07, top - 0.1, report.t("Як цитувати", "How to cite"), color=INK, fontsize=12, fontweight="bold")
        canvas.text(0.07, top - 0.13, _wrap(citation, 86), color=INK, fontsize=8.5, va="top", family="DejaVu Sans Mono")
        canvas.text(0.07, 0.035, f"TerraTrend Detective · {report.t('справа', 'case')} {report.case_id} · {report.generated_at}", color=MUTED, fontsize=8)
        pdf.savefig(page)
        plt.close(page)
    return buffer.getvalue()
