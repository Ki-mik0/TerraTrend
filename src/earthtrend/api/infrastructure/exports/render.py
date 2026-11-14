"""One file per export format. Numbers are copied from the stored case."""

from __future__ import annotations

import csv
import io
import json
import struct
import zipfile
import zlib

from jinja2 import Environment

from earthtrend.api.domain.cases.model import Case

MEDIA = {
    "csv": "text/csv",
    "geojson": "application/geo+json",
    "ipynb": "application/x-ipynb+json",
    "html": "text/html",
    "png": "image/png",
    "pdf": "application/pdf",
    "zip": "application/zip",
    "nc": "application/netcdf",
    "svg": "image/svg+xml",
    "citation": "text/plain",
}

DATASET_DOI = {
    "gldas_sm": "10.5067/SXAVCZFAQLNO",
    "merra2_t2m": "10.5067/VJAFPLI1CSIV",
}

_HTML = Environment(autoescape=True).from_string(
    "<!DOCTYPE html><html><body>"
    "<p>variable {{ variable_id }}</p>"
    "<p>region {{ region_id }}</p>"
    "<p>verdict {{ verdict }}</p>"
    "<p>slope {{ slope }}</p>"
    "</body></html>"
)


def render(case: Case, fmt: str) -> bytes:
    if fmt == "csv":
        return _csv(case)
    if fmt == "geojson":
        return _geojson(case)
    if fmt == "ipynb":
        return _notebook(case)
    if fmt == "html":
        return _html(case)
    if fmt == "png":
        return _png(_facts(case)["slope"])
    if fmt == "pdf":
        return _pdf(case)
    if fmt == "svg":
        return _svg(case)
    if fmt == "nc":
        return _netcdf(_slope(case))
    if fmt == "zip":
        return _zip(case)
    return _citation(case).encode("utf-8")


def _facts(case: Case) -> dict[str, str]:
    slope = "" if case.series is None else str(case.series.slope_decade)
    verdict = "" if case.verdict is None else case.verdict.code
    confirmed = "" if case.evidence is None else str(case.evidence.witnesses.confirmed)
    total = "" if case.evidence is None else str(case.evidence.witnesses.total)
    return {
        "variable_id": case.spec.variable_id,
        "region_id": case.spec.region_id,
        "period_start": case.spec.period_start,
        "period_end": case.spec.period_end,
        "verdict": verdict,
        "slope": slope,
        "witnesses_confirmed": confirmed,
        "witnesses_total": total,
    }


def _slope(case: Case) -> float:
    if case.series is None:
        return 0.0
    return case.series.slope_decade


def _csv(case: Case) -> bytes:
    facts = _facts(case)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(facts))
    writer.writeheader()
    writer.writerow(facts)
    return buffer.getvalue().encode("utf-8")


def _geojson(case: Case) -> bytes:
    facts = _facts(case)
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": None,
                "properties": {
                    "variable_id": facts["variable_id"],
                    "region_id": facts["region_id"],
                    "verdict": facts["verdict"],
                    "slope_decade": _slope(case),
                    "witnesses_confirmed": facts["witnesses_confirmed"],
                },
            }
        ],
    }
    return json.dumps(payload).encode("utf-8")


def _notebook(case: Case) -> bytes:
    facts = _facts(case)
    source = f"verdict {facts['verdict']}\nslope {facts['slope']}\n"
    payload = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [source],
            }
        ],
    }
    return json.dumps(payload).encode("utf-8")


def _html(case: Case) -> bytes:
    return _HTML.render(**_facts(case)).encode("utf-8")


def _svg(case: Case) -> bytes:
    facts = _facts(case)
    text = f"verdict {facts['verdict']} slope {facts['slope']}"
    body = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="48">'
        f"<text x=\"8\" y=\"28\">{text}</text></svg>"
    )
    return body.encode("utf-8")


def _citation(case: Case) -> str:
    facts = _facts(case)
    lines = [
        f"EarthTrend case {case.id}.",
        (
            f"{facts['variable_id']} in {facts['region_id']}: "
            f"slope {facts['slope']} per decade, verdict {facts['verdict']}."
        ),
    ]
    doi = DATASET_DOI.get(facts["variable_id"])
    if doi is not None:
        lines.append(f"Dataset DOI: {doi}.")
    return "\n".join(lines) + "\n"


def _png(slope: str) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    text = b"slope_decade\x00" + slope.encode("ascii")
    scanline = zlib.compress(b"\x00\x80")
    return (
        signature
        + chunk(b"IHDR", ihdr)
        + chunk(b"tEXt", text)
        + chunk(b"IDAT", scanline)
        + chunk(b"IEND", b"")
    )


def _pdf(case: Case) -> bytes:
    facts = _facts(case)
    shown = f"verdict {facts['verdict']} slope {facts['slope']}"
    stream = f"BT /F1 12 Tf 40 100 Td ({shown}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    header = b"%PDF-1.4\n"
    body = b""
    offsets = [0]
    cursor = len(header)
    for number, payload in enumerate(objects, start=1):
        encoded = f"{number} 0 obj\n".encode("ascii") + payload + b"\nendobj\n"
        offsets.append(cursor)
        body += encoded
        cursor += len(encoded)
    xref = b"xref\n" + f"0 {len(offsets)}\n".encode("ascii") + b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        xref += f"{offset:010d} 00000 n \n".encode("ascii")
    trailer = (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{cursor}\n%%EOF\n".encode("ascii")
    )
    return header + body + xref + trailer


def _netcdf(slope: float) -> bytes:
    def name(text: str) -> bytes:
        raw = text.encode("ascii")
        pad = (4 - (len(raw) % 4)) % 4
        return struct.pack(">I", len(raw)) + raw + (b"\x00" * pad)

    header = b"".join(
        (
            b"CDF\x01",
            struct.pack(">I", 0),
            struct.pack(">II", 0, 0),
            struct.pack(">II", 0, 0),
            struct.pack(">II", 11, 1),
            name("slope_decade"),
            struct.pack(">I", 0),
            struct.pack(">II", 0, 0),
            struct.pack(">I", 5),
            struct.pack(">I", 4),
        )
    )
    begin = len(header) + 4
    return header + struct.pack(">I", begin) + struct.pack(">f", slope)


def _zip(case: Case) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("case.csv", _csv(case))
        archive.writestr("citation.txt", _citation(case))
    return buffer.getvalue()
