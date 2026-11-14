"""Identity against a real PostgreSQL. Skipped when the database is down."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.domain.identity.model import IdentityError, User
from earthtrend.api.infrastructure.identity.crypto import ArgonPassword, JwtTokens
from earthtrend.api.infrastructure.identity.postgres import Base, PostgresIdentityStore
from earthtrend.api.infrastructure.identity.wiring import MemoryCaseLookup, identity_from_env

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.environ.get(
    "DB_URL",
    "postgresql+asyncpg://earthtrend:earthtrend@127.0.0.1:5432/earthtrend",
)
MOMENT = datetime(2024, 2, 29, 12, 0, tzinfo=timezone.utc)


class FixedClock:
    def now(self) -> datetime:
        return MOMENT


def _engine(url: str):
    return create_async_engine(url, poolclass=NullPool)


async def _reachable(url: str) -> None:
    engine = _engine(url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def postgres_url() -> str:
    if not DATABASE_URL.startswith("postgresql"):
        pytest.skip("DB_URL is not PostgreSQL")
    try:
        asyncio.run(_reachable(DATABASE_URL))
    except Exception as error:
        pytest.skip(f"PostgreSQL is not reachable: {error}")
    return DATABASE_URL


@pytest.fixture
async def database(postgres_url: str):
    engine = _engine(postgres_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text("TRUNCATE TABLE api_keys, audit_logs, ai_reviews, identity_counters, users RESTART IDENTITY CASCADE")
        )
    passwords = ArgonPassword()
    store = PostgresIdentityStore(engine, passwords=passwords, clock=FixedClock())
    yield store, engine, passwords
    await engine.dispose()


def _service(store: PostgresIdentityStore, passwords: ArgonPassword, cases: dict | None = None) -> IdentityService:
    return IdentityService(
        passwords=passwords,
        tokens=JwtTokens(),
        cases=MemoryCaseLookup(cases),
        store=store,
    )


async def _scalar(engine, statement: str, **params):
    async with engine.connect() as connection:
        return await connection.scalar(text(statement), params)


async def test_parallel_signup_keeps_one_row_and_the_original_role(database) -> None:
    store, engine, passwords = database
    service = _service(store, passwords)
    results = await asyncio.gather(
        service.add_user(user_id="a", username="ada", role="user", password="secret"),
        service.add_user(user_id="b", username="ada", role="admin", password="other"),
        return_exceptions=True,
    )
    assert sum(isinstance(item, User) for item in results) == 1
    assert any(isinstance(item, IdentityError) and item.code == "username_taken" for item in results)
    winner = next(item for item in results if isinstance(item, User))
    assert await _scalar(engine, "SELECT count(*) FROM users") == 1
    assert await _scalar(engine, "SELECT role FROM users WHERE username = :username", username="ada") == winner.role


async def test_bad_audit_action_rolls_back_the_key(database) -> None:
    store, engine, passwords = database
    await store.add_user(User(id="admin", username="ada", role="admin", password_hash=passwords.hash("secret")))
    with pytest.raises(IntegrityError):
        await store.write_key_and_audit(
            owner_id="admin",
            key_id="key_x",
            secret_hash="hash",
            actor_id="admin",
            action="nope",
            subject_id="key_x",
        )
    assert await _scalar(engine, "SELECT count(*) FROM api_keys") == 0
    assert await _scalar(engine, "SELECT count(*) FROM audit_logs") == 0


async def test_key_hash_audit_time_and_indexes(database) -> None:
    store, engine, passwords = database
    service = _service(store, passwords)
    await service.add_user(user_id="admin", username="ada", role="admin", password="secret")
    key = await service.issue_key(actor_id="admin", role="admin", owner_id="admin")
    stored = await _scalar(engine, "SELECT secret_hash FROM api_keys WHERE id = :id", id=key.id)
    assert stored != key.secret
    assert stored.startswith("$argon2")
    assert await _scalar(engine, "SELECT created_at FROM audit_logs WHERE subject_id = :id", id=key.id) == MOMENT
    await service.revoke_key(actor_id="admin", role="admin", key_id=key.id)
    with pytest.raises(IdentityError):
        await service.revoke_key(actor_id="admin", role="admin", key_id=key.id)
    assert await _scalar(engine, "SELECT count(*) FROM audit_logs") == 2
    names = await _scalar(
        engine,
        "SELECT string_agg(indexname, ',') FROM pg_indexes WHERE tablename IN ('users', 'api_keys', 'audit_logs')",
    )
    assert "api_keys_active_user" in names
    assert "audit_logs_actor" in names
    assert "users_username_key" in names


async def test_login_writes_one_user_and_a_stranger_quote_does_not_match(database) -> None:
    store, engine, passwords = database
    service = _service(store, passwords)
    await service.add_user(user_id="admin", username="ada", role="admin", password="secret")
    with pytest.raises(IdentityError) as caught:
        await service.login(username="ada' OR '1'='1", password="secret")
    assert caught.value.code == "invalid_credentials"
    await service.login(username="ada", password="secret")
    await service.login(username="ada", password="secret")
    assert await _scalar(engine, "SELECT count(*) FROM users") == 1


async def test_register_survives_a_new_process_and_stores_a_hash(database) -> None:
    store, engine, passwords = database
    service = _service(store, passwords)
    token = await service.register(username="ada", password="secret")
    user_id, role = await service.read_session(token)
    assert user_id == "user-1" and role == "user"
    again = PostgresIdentityStore(engine, passwords=passwords, clock=FixedClock())
    loaded = await again.get_by_username("ada")
    assert loaded is not None
    assert loaded.id == "user-1"
    assert loaded.role == "user"
    assert loaded.password_hash != "secret"
    assert loaded.password_hash.startswith("$argon2")
    assert passwords.verify("secret", loaded.password_hash)
    with pytest.raises(IdentityError) as caught:
        await service.register(username="ada", password="other")
    assert caught.value.code == "username_taken"
    assert await _scalar(engine, "SELECT count(*) FROM users WHERE username = 'ada'") == 1
    second = await service.register(username="bea", password="secret")
    assert await service.read_session(second) == ("user-2", "user")


async def test_env_builder_prepares_postgres_and_a_redis_client(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_URL", postgres_url)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    service, prepare = identity_from_env()
    assert prepare is not None
    await prepare()
    await service._store.engine.dispose()
    cache = service._cache
    await cache._client.aclose()


async def test_unreachable_database_raises_and_writes_nothing(postgres_url: str) -> None:
    engine = create_async_engine(
        "postgresql+asyncpg://earthtrend:earthtrend@127.0.0.1:1/earthtrend",
        poolclass=NullPool,
        connect_args={"connect_timeout": 2},
    )
    store = PostgresIdentityStore(engine, passwords=ArgonPassword(), clock=FixedClock())
    with pytest.raises(Exception):
        await store.add_user(User(id="u", username="ada", role="user", password_hash="x"))
    await engine.dispose()


async def test_migration_roundtrip_restores_the_identity_tables(postgres_url: str) -> None:
    admin = _engine(postgres_url)
    async with admin.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text("DROP DATABASE IF EXISTS earthtrend_mig"))
        await autocommit.execute(text("CREATE DATABASE earthtrend_mig"))
    await admin.dispose()
    mig_url = postgres_url.rsplit("/", 1)[0] + "/earthtrend_mig"
    sync_url = mig_url.replace("postgresql+asyncpg", "postgresql+psycopg")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    probe = _engine(mig_url)
    async with probe.connect() as connection:
        tables = await connection.scalar(
            text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users'")
        )
    assert tables == 0
    command.upgrade(config, "head")
    async with probe.connect() as connection:
        tables = await connection.scalar(
            text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users'")
        )
    assert tables == 1
    await probe.dispose()
    async with _engine(postgres_url).connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text("DROP DATABASE IF EXISTS earthtrend_mig"))
