import asyncio
import re

import pytest
from litestar.testing import TestClient

from earthtrend.api.application.exports.service import ExportService
from earthtrend.api.domain.exports.model import ExportError, require_format
from earthtrend.api.infrastructure.cases.memory import MemoryCaseStore
from earthtrend.api.infrastructure.cases.wiring import build_case_service
from earthtrend.api.infrastructure.identity.wiring import build_identity_service
from earthtrend.api.main import create_app

BODY = {
    "variable_id": "gldas_sm",
    "region_id": "ukraine_south",
    "period_start": "2000-01",
    "period_end": "2025-12",
}


def test_unknown_format_does_not_create_a_file() -> None:
    with pytest.raises(ExportError) as caught:
        require_format("docx")
    assert caught.value.code == "format_invalid"
    store = MemoryCaseStore()
    service = ExportService(cases=store)
    with pytest.raises(ExportError):
        import asyncio

        asyncio.run(service.create(case_id="missing", fmt="docx", actor_id="u1"))
    assert service.records == {}


def test_csv_download_contains_case_slope_and_stranger_is_refused() -> None:
    store = MemoryCaseStore()
    identity = build_identity_service()
    asyncio.run(identity.add_user(user_id="u1", username="u1", role="user", password="secret"))
    asyncio.run(identity.add_user(user_id="u2", username="u2", role="user", password="secret"))
    app = create_app(cases=build_case_service(store=store), exports=ExportService(cases=store), identity=identity)
    with TestClient(app) as client:
        owner = {
            "Authorization": "Bearer "
            + client.post("/api/v1/session", json={"username": "u1", "password": "secret"}).json()["token"]
        }
        stranger = {
            "Authorization": "Bearer "
            + client.post("/api/v1/session", json={"username": "u2", "password": "secret"}).json()["token"]
        }
        created = client.post("/api/v1/cases", json=BODY, headers=owner)
        case_id = created.json()["id"]
        queued = client.post(f"/api/v1/cases/{case_id}/export", json={"format": "csv"}, headers=owner)
        assert queued.status_code == 202
        export_id = queued.json()["id"]
        ready = client.get(f"/api/v1/exports/{export_id}", headers=owner)
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"
        downloaded = client.get(f"/api/v1/exports/{export_id}/download", headers=owner)
        assert downloaded.status_code == 200
        assert downloaded.headers["content-type"].startswith("text/csv")
        text = downloaded.content.decode()
        assert "-0.21" in text
        assert "strong" in text
        hidden = client.get(f"/api/v1/exports/{export_id}/download", headers=stranger)
        assert hidden.status_code == 404


def _download(client: TestClient, headers: dict[str, str], case_id: str, fmt: str) -> bytes:
    queued = client.post(f"/api/v1/cases/{case_id}/export", json={"format": fmt}, headers=headers)
    assert queued.status_code == 202
    export_id = queued.json()["id"]
    downloaded = client.get(f"/api/v1/exports/{export_id}/download", headers=headers)
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith(
        {
            "csv": "text/csv",
            "geojson": "application/geo+json",
            "ipynb": "application/x-ipynb+json",
            "html": "text/html",
            "png": "image/png",
            "pdf": "application/pdf",
            "zip": "application/zip",
            "nc": "application/x-netcdf",
            "svg": "image/svg+xml",
            "citation": "text/plain",
        }[fmt]
    )
    return downloaded.content


def test_each_format_is_its_own_file_with_the_case_slope() -> None:
    import json
    import struct
    import zipfile
    from io import BytesIO

    store = MemoryCaseStore()
    identity = build_identity_service()
    asyncio.run(identity.add_user(user_id="u1", username="u1", role="user", password="secret"))
    app = create_app(cases=build_case_service(store=store), exports=ExportService(cases=store), identity=identity)
    with TestClient(app) as client:
        headers = {
            "Authorization": "Bearer "
            + client.post("/api/v1/session", json={"username": "u1", "password": "secret"}).json()["token"]
        }
        case_id = client.post("/api/v1/cases", json=BODY, headers=headers).json()["id"]
        files = {fmt: _download(client, headers, case_id, fmt) for fmt in (
            "csv",
            "geojson",
            "ipynb",
            "html",
            "png",
            "pdf",
            "svg",
            "nc",
            "zip",
            "citation",
        )}

    assert files["csv"] != files["pdf"]
    assert files["csv"].startswith("\ufeff".encode())  # BOM, so Excel reads Cyrillic
    assert b"year,-0.21" in files["csv"] and b"strong" in files["csv"]
    geo = json.loads(files["geojson"])
    assert geo["type"] == "FeatureCollection"
    assert geo["features"][0]["properties"]["change_per_decade"] == -0.21
    assert geo["features"][0]["properties"]["verdict"] == "strong"
    notebook = json.loads(files["ipynb"])
    assert notebook["nbformat"] == 4
    assert "-0.21" in "".join("".join(cell["source"]) for cell in notebook["cells"])
    assert b"<html" in files["html"] and b"0.21" in files["html"] and b"<svg" in files["html"]
    assert files["png"].startswith(b"\x89PNG")
    from PIL import Image

    assert Image.open(BytesIO(files["png"])).size == (1200, 630)
    assert files["pdf"].startswith(b"%PDF") and files["pdf"].rstrip().endswith(b"%%EOF")
    assert re.search(rb"/Count 2\b", files["pdf"])  # two A4 pages
    assert files["svg"].lstrip().startswith((b"<?xml", b"<svg"))
    assert files["nc"].startswith(b"CDF")
    assert b"@misc" in files["citation"] and b"case_" in files["citation"]
    with zipfile.ZipFile(BytesIO(files["zip"])) as archive:
        names = set(archive.namelist())
        assert {"README.md", "report.html", "report.pdf", "card.png", "chart.svg", "data.csv", "citation.txt"} <= names
        assert b"year,-0.21" in archive.read("data.csv")


def test_download_names_the_file_and_report_follows_language() -> None:
    store = MemoryCaseStore()
    identity = build_identity_service()
    asyncio.run(identity.add_user(user_id="u1", username="u1", role="user", password="secret"))
    app = create_app(cases=build_case_service(store=store), exports=ExportService(cases=store), identity=identity)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + client.post("/api/v1/session", json={"username": "u1", "password": "secret"}).json()["token"]}
        case_id = client.post("/api/v1/cases", json=BODY, headers=headers).json()["id"]
        queued = client.post(f"/api/v1/cases/{case_id}/export", json={"format": "citation", "language": "en"}, headers=headers).json()
        assert queued["filename"] == "terratrend-gldas-sm-ukraine-south-2000-2025.txt"
        downloaded = client.get(queued["download_url"], headers=headers)
        assert downloaded.headers["content-disposition"] == 'attachment; filename="terratrend-gldas-sm-ukraine-south-2000-2025.txt"'
        assert b"Verdict" in downloaded.content or b"verdict" in downloaded.content.lower()
        uk = client.post(f"/api/v1/cases/{case_id}/export", json={"format": "html", "language": "uk"}, headers=headers).json()
        assert "Вирок".encode() in client.get(uk["download_url"], headers=headers).content


def test_unknown_variable_citation_has_no_invented_dataset_doi() -> None:
    from earthtrend.api.domain.cases.model import Case, CaseSpec
    from earthtrend.api.infrastructure.exports.render import render

    case = Case(
        id="c",
        owner_id="u",
        role="user",
        spec=CaseSpec("other_var", "somewhere", "2000-01", "2025-12"),
    )
    text = render(case, "citation").decode()
    assert "other_var" in text
    assert "10.5067" not in text
