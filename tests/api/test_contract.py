"""The committed OpenAPI contract must match the running API, so the web app never drifts."""

from pathlib import Path

from litestar.testing import TestClient

from earthtrend.api import contract
from earthtrend.api.main import create_app


def test_scalar_docs_are_served_at_schema() -> None:
    with TestClient(create_app()) as client:
        page = client.get("/schema")
        alias = client.get("/schema/scalar")
        spec = client.get("/schema/openapi.json")
    assert page.status_code == 200
    assert "scalar" in page.text.casefold()
    assert alias.status_code == 200
    assert alias.text == page.text
    assert spec.status_code == 200
    assert spec.json()["info"]["title"] == "EarthTrend API"


def test_committed_contract_matches_api() -> None:
    assert contract.check(), (
        "contract/openapi.json is out of date with the API. "
        "Run `python scripts/contract.py --web` and commit the result."
    )


def test_write_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    assert contract.write(target) is True
    assert contract.write(target) is False
    assert contract.check(target) is True


def test_check_detects_drift(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    assert contract.check(target) is False
    target.write_text("{}\n", encoding="utf-8")
    assert contract.check(target) is False


def test_cli_write_then_check(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(contract, "CONTRACT", tmp_path / "contract" / "openapi.json")
    monkeypatch.setattr(contract, "_regenerate_web", lambda: print("web regenerated"))

    assert contract.main(["--check"]) == 1
    assert "out of date" in capsys.readouterr().err

    assert contract.main(["--web"]) == 0
    out = capsys.readouterr().out
    assert "updated" in out and "web regenerated" in out

    assert contract.main(["--check"]) == 0
    assert contract.main([]) == 0
    assert "unchanged" in capsys.readouterr().out


def test_regenerate_web_skips_without_node_modules(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(contract, "WEB", tmp_path)
    contract._regenerate_web()
    assert "skip web types" in capsys.readouterr().err
