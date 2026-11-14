"""Sign in, read a session, manage API keys, and record an AI disagreement review."""

from __future__ import annotations

from typing import Protocol

from earthtrend.api.application.identity.store import IdentityStore, UserCache
from earthtrend.api.domain.cases.model import Case
from earthtrend.api.domain.identity.model import AiReview, ApiKey, AuditRecord, IdentityError, User, allows
from earthtrend.api.infrastructure.identity.cache import NullUserCache


ADMIN_ACTIONS = frozenset({"warm_cache", "clear_cache", "reload_catalog"})


class PasswordPort(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password: str, password_hash: str) -> bool: ...


class TokenPort(Protocol):
    def issue(self, *, user_id: str, role: str) -> str: ...

    def read(self, token: str) -> tuple[str, str]: ...


class CaseLookup(Protocol):
    async def get(self, case_id: str) -> Case | None: ...


class IdentityService:
    def __init__(
        self,
        *,
        passwords: PasswordPort,
        tokens: TokenPort,
        cases: CaseLookup,
        store: IdentityStore,
        cache: UserCache | None = None,
    ) -> None:
        self._passwords = passwords
        self._tokens = tokens
        self._cases = cases
        self._store = store
        self._cache = cache if cache is not None else NullUserCache()
        self.audit = store.audit
        self.reviews: list[AiReview] = []

    async def add_user(self, *, user_id: str, username: str, role: str, password: str) -> User:
        user = User(
            id=user_id,
            username=username,
            role=role,
            password_hash=self._passwords.hash(password),
        )
        await self._store.add_user(user)
        return user

    async def login(self, *, username: str, password: str) -> str:
        user = await self._store.get_by_username(username)
        if user is None or not self._passwords.verify(password, user.password_hash):
            raise IdentityError("invalid_credentials", "Невірний пароль")
        await self._remember(user)
        return self._tokens.issue(user_id=user.id, role=user.role)

    async def issue_guest(self) -> str:
        user = await self._store.insert_guest()
        await self._remember(user)
        return self._tokens.issue(user_id=user.id, role="guest")

    async def register(self, *, username: str, password: str) -> str:
        if password == "":
            raise IdentityError("password_empty", "Порожній пароль")
        if username.strip() == "":
            raise IdentityError("username_invalid", "Порожнє ім’я")
        user = await self._store.insert_user(
            username=username,
            password_hash=self._passwords.hash(password),
        )
        await self._remember(user)
        return self._tokens.issue(user_id=user.id, role=user.role)

    async def read_session(self, token: str) -> tuple[str, str]:
        try:
            user_id, role = self._tokens.read(token)
        except Exception as error:
            raise IdentityError("invalid_token", "Сесія недійсна") from error
        user = await self._cached_user(user_id)
        if user is None or user.role != role:
            raise IdentityError("invalid_token", "Сесія недійсна")
        return user.id, user.role

    async def issue_key(self, *, actor_id: str, role: str, owner_id: str) -> ApiKey:
        self._require_admin(role)
        return await self._store.issue_key(actor_id=actor_id, owner_id=owner_id)

    async def revoke_key(self, *, actor_id: str, role: str, key_id: str) -> None:
        self._require_admin(role)
        await self._store.revoke_key(actor_id=actor_id, key_id=key_id)

    async def review(self, *, actor_id: str, role: str, case_id: str, note: str) -> AiReview:
        self._require_admin(role)
        if note.strip() == "":
            raise IdentityError("note_empty", "Порожня нотатка")
        case = await self._cases.get(case_id)
        if case is None:
            raise IdentityError("case_not_found", "Справу не знайдено")
        if case.ai_opinion is None or not case.ai_opinion.disagrees:
            raise IdentityError("review_not_allowed", "Рев’ю лише для розбіжності ШІ")
        review_id = await self._store.add_review(actor_id=actor_id, case_id=case_id, note=note)
        created = AiReview(id=review_id, case_id=case_id, actor_id=actor_id, note=note)
        self.reviews.append(created)
        return created

    async def record_admin(self, *, actor_id: str, role: str, action: str, subject_id: str) -> AuditRecord:
        """Audit row for an admin action of another zone (cache warm-up, cache clear, catalog reload)."""
        self._require_admin(role)
        if action not in ADMIN_ACTIONS:
            raise IdentityError("action_unknown", "Невідома адмін-дія")
        return await self._store.record_admin(actor_id=actor_id, action=action, subject_id=subject_id)

    async def _cached_user(self, user_id: str) -> User | None:
        try:
            cached = await self._cache.get(user_id)
        except Exception:
            cached = None
        if cached is not None:
            return cached
        found = await self._store.get_by_id(user_id)
        if found is not None:
            await self._remember(found)
        return found

    async def _remember(self, user: User) -> None:
        try:
            await self._cache.put(user)
        except Exception:
            return

    def _require_admin(self, role: str) -> None:
        if not allows(role, "admin"):
            raise IdentityError("forbidden", "Це може зробити лише admin")
