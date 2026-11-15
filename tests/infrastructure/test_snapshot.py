import asyncio
from pathlib import Path

from earthtrend.api.domain.cases.model import CaseSpec
from earthtrend.api.infrastructure.cases.memory import MemoryCaseStore
from earthtrend.api.infrastructure.cases.wiring import build_case_service
from earthtrend.api.infrastructure.identity.clock import SystemClock
from earthtrend.api.infrastructure.identity.crypto import ArgonPassword
from earthtrend.api.infrastructure.identity.memory_store import MemoryIdentityStore
from earthtrend.api.infrastructure.shared.snapshot import persist, state_dir


def test_cases_and_users_survive_a_restart(tmp_path: Path) -> None:
    def boot() -> tuple[MemoryCaseStore, MemoryIdentityStore]:
        cases = persist(MemoryCaseStore(), "cases", ("cases", "_seq"), directory=tmp_path)
        users = persist(
            MemoryIdentityStore(passwords=ArgonPassword(), clock=SystemClock()),
            "identity",
            ("users", "audit", "reviews", "secret_hashes", "_counters"),
            directory=tmp_path,
        )
        return cases, users

    cases, users = boot()
    guest = asyncio.run(users.insert_guest())
    service = build_case_service(store=cases)
    created = asyncio.run(service.create(spec=CaseSpec("gldas_sm", "ukraine_south", "2000-01", "2025-12"), owner_id=guest.id, role="user"))

    cases, users = boot()  # a new process reads what the old one wrote
    restored = asyncio.run(cases.get(created.id))
    assert restored is not None and restored.owner_id == guest.id
    assert restored.series is not None and restored.series.slope_decade == created.series.slope_decade
    assert asyncio.run(users.get_by_id(guest.id)) is not None
    assert asyncio.run(cases.next_id()) != created.id  # numbering goes on, ids are never reused
    assert asyncio.run(users.insert_guest()).id != guest.id


def test_a_broken_snapshot_starts_clean(tmp_path: Path) -> None:
    (tmp_path / "cases.pickle").write_bytes(b"not a pickle")
    cases = persist(MemoryCaseStore(), "cases", ("cases", "_seq"), directory=tmp_path)
    assert cases.cases == {}


def test_state_dir_is_off_in_tests_and_can_be_forced(monkeypatch) -> None:
    monkeypatch.delenv("STATE_DIR", raising=False)
    assert state_dir() is None
    monkeypatch.setenv("STATE_DIR", "custom")
    assert state_dir() == Path("custom")
    monkeypatch.setenv("STATE_DIR", "off")
    assert state_dir() is None
