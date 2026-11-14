"""PostgreSQL identity tables. One transaction writes a key or a review together with its audit row."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from earthtrend.api.application.identity.store import Clock
from earthtrend.api.domain.identity.model import ApiKey, AuditRecord, IdentityError, User
from earthtrend.api.infrastructure.identity.crypto import ArgonPassword


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('guest', 'user', 'teacher', 'admin')", name="users_role_known"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)


class ApiKeyRow(Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("api_keys_active_user", "user_id", postgresql_where=text("revoked = false")),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    secret_hash: Mapped[str] = mapped_column(Text, nullable=False)
    revoked: Mapped[bool] = mapped_column(nullable=False, default=False)


class AuditRow(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "action IN ('issue_key', 'revoke_key', 'ai_review', 'warm_cache', 'clear_cache', 'reload_catalog')",
            name="audit_action_known",
        ),
        Index("audit_logs_actor", "actor_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewRow(Base):
    __tablename__ = "ai_reviews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)


class CounterRow(Base):
    __tablename__ = "identity_counters"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)


def _user(row: UserRow) -> User:
    return User(id=row.id, username=row.username, role=row.role, password_hash=row.password_hash)


class PostgresIdentityStore:
    def __init__(self, engine: AsyncEngine, *, passwords: ArgonPassword, clock: Clock) -> None:
        self.engine = engine
        self._passwords = passwords
        self._clock = clock
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self.audit: list[AuditRecord] = []

    async def add_user(self, user: User) -> None:
        try:
            async with self._sessions() as session:
                async with session.begin():
                    session.add(
                        UserRow(
                            id=user.id,
                            username=user.username,
                            role=user.role,
                            password_hash=user.password_hash,
                        )
                    )
        except IntegrityError as error:
            raise IdentityError("username_taken", "Ім’я вже зайняте") from error

    async def get_by_username(self, username: str) -> User | None:
        async with self._sessions() as session:
            found = await session.scalar(select(UserRow).where(UserRow.username == username))
        return None if found is None else _user(found)

    async def get_by_id(self, user_id: str) -> User | None:
        async with self._sessions() as session:
            found = await session.get(UserRow, user_id)
        return None if found is None else _user(found)

    async def insert_guest(self) -> User:
        async with self._sessions() as session:
            async with session.begin():
                number = await self._next(session, "guest")
                user = User(
                    id=f"guest-{number}",
                    username=f"guest-{number}",
                    role="guest",
                    password_hash="",
                )
                session.add(
                    UserRow(id=user.id, username=user.username, role=user.role, password_hash=user.password_hash)
                )
        return user

    async def insert_user(self, *, username: str, password_hash: str) -> User:
        try:
            async with self._sessions() as session:
                async with session.begin():
                    number = await self._next(session, "user")
                    user = User(
                        id=f"user-{number}",
                        username=username,
                        role="user",
                        password_hash=password_hash,
                    )
                    session.add(
                        UserRow(
                            id=user.id,
                            username=user.username,
                            role=user.role,
                            password_hash=user.password_hash,
                        )
                    )
            return user
        except IntegrityError as error:
            raise IdentityError("username_taken", "Ім’я вже зайняте") from error

    async def issue_key(self, *, actor_id: str, owner_id: str) -> ApiKey:
        async with self._sessions() as session:
            async with session.begin():
                owner = await session.get(UserRow, owner_id)
                if owner is None:
                    raise IdentityError("user_not_found", "Користувача не знайдено")
                number = await self._next(session, "key")
                secret = f"secret_{number}"
                key = ApiKey(id=f"key_{number}", secret=secret)
                session.add(
                    ApiKeyRow(
                        id=key.id,
                        user_id=owner_id,
                        secret_hash=self._passwords.hash(secret),
                        revoked=False,
                    )
                )
                record = await self._add_audit(session, actor_id=actor_id, action="issue_key", subject_id=key.id)
        self.audit.append(record)
        return key

    async def revoke_key(self, *, actor_id: str, key_id: str) -> None:
        async with self._sessions() as session:
            async with session.begin():
                key = await session.get(ApiKeyRow, key_id)
                if key is None or key.revoked:
                    raise IdentityError("key_not_found", "Ключ не знайдено")
                key.revoked = True
                record = await self._add_audit(session, actor_id=actor_id, action="revoke_key", subject_id=key_id)
        self.audit.append(record)

    async def add_review(self, *, actor_id: str, case_id: str, note: str) -> str:
        async with self._sessions() as session:
            async with session.begin():
                number = await self._next(session, "review")
                review_id = f"review_{number}"
                session.add(ReviewRow(id=review_id, case_id=case_id, actor_id=actor_id, note=note))
                record = await self._add_audit(session, actor_id=actor_id, action="ai_review", subject_id=review_id)
        self.audit.append(record)
        return review_id

    async def record_admin(self, *, actor_id: str, action: str, subject_id: str) -> AuditRecord:
        async with self._sessions() as session:
            async with session.begin():
                record = await self._add_audit(session, actor_id=actor_id, action=action, subject_id=subject_id)
        self.audit.append(record)
        return record

    async def write_key_and_audit(
        self, *, owner_id: str, key_id: str, secret_hash: str, actor_id: str, action: str, subject_id: str
    ) -> None:
        async with self._sessions() as session:
            async with session.begin():
                owner = await session.get(UserRow, owner_id)
                if owner is None:
                    raise IdentityError("user_not_found", "Користувача не знайдено")
                session.add(ApiKeyRow(id=key_id, user_id=owner_id, secret_hash=secret_hash, revoked=False))
                await self._add_audit(session, actor_id=actor_id, action=action, subject_id=subject_id)

    async def _next(self, session: AsyncSession, name: str) -> int:
        row = await session.get(CounterRow, name, with_for_update=True)
        if row is None:
            session.add(CounterRow(name=name, value=1))
            await session.flush()
            return 1
        row.value += 1
        return row.value

    async def _add_audit(self, session: AsyncSession, *, actor_id: str, action: str, subject_id: str) -> AuditRecord:
        number = await self._next(session, "audit")
        created_at = self._clock.now()
        session.add(
            AuditRow(
                id=f"audit_{number}",
                actor_id=actor_id,
                action=action,
                subject_id=subject_id,
                created_at=created_at,
            )
        )
        return AuditRecord(
            id=f"audit_{number}",
            actor_id=actor_id,
            action=action,
            subject_id=subject_id,
            created_at=created_at,
        )
