"""In-memory identity store. Tests and a process without PostgreSQL use it."""

from __future__ import annotations

from earthtrend.api.application.identity.store import Clock
from earthtrend.api.domain.identity.model import ApiKey, AuditRecord, IdentityError, User
from earthtrend.api.infrastructure.identity.crypto import ArgonPassword


class MemoryIdentityStore:
    def __init__(self, *, passwords: ArgonPassword, clock: Clock) -> None:
        self._passwords = passwords
        self._clock = clock
        self.users: dict[str, User] = {}
        self.audit: list[AuditRecord] = []
        self.reviews: list[tuple[str, str, str, str]] = []
        self.secret_hashes: dict[str, str] = {}
        self._counters = {"guest": 0, "user": 0, "key": 0, "audit": 0, "review": 0}

    def _next(self, name: str) -> int:
        self._counters[name] += 1
        return self._counters[name]

    async def add_user(self, user: User) -> None:
        if any(item.username == user.username for item in self.users.values()):
            raise IdentityError("username_taken", "Ім’я вже зайняте")
        self.users[user.id] = user

    async def get_by_username(self, username: str) -> User | None:
        return next((item for item in self.users.values() if item.username == username), None)

    async def get_by_id(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    async def insert_guest(self) -> User:
        number = self._next("guest")
        user = User(
            id=f"guest-{number}",
            username=f"guest-{number}",
            role="guest",
            password_hash="",
        )
        self.users[user.id] = user
        return user

    async def insert_user(self, *, username: str, password_hash: str) -> User:
        if any(item.username == username for item in self.users.values()):
            raise IdentityError("username_taken", "Ім’я вже зайняте")
        number = self._next("user")
        user = User(
            id=f"user-{number}",
            username=username,
            role="user",
            password_hash=password_hash,
        )
        self.users[user.id] = user
        return user

    async def issue_key(self, *, actor_id: str, owner_id: str) -> ApiKey:
        owner = self.users.get(owner_id)
        if owner is None:
            raise IdentityError("user_not_found", "Користувача не знайдено")
        number = self._next("key")
        secret = f"secret_{number}"
        key = ApiKey(id=f"key_{number}", secret=secret)
        self.secret_hashes[key.id] = self._passwords.hash(secret)
        owner.keys.append(key)
        self._remember_audit(actor_id, "issue_key", key.id)
        return key

    async def revoke_key(self, *, actor_id: str, key_id: str) -> None:
        for user in self.users.values():
            for key in user.keys:
                if key.id == key_id and not key.revoked:
                    key.revoked = True
                    self._remember_audit(actor_id, "revoke_key", key.id)
                    return
        raise IdentityError("key_not_found", "Ключ не знайдено")

    async def add_review(self, *, actor_id: str, case_id: str, note: str) -> str:
        number = self._next("review")
        review_id = f"review_{number}"
        self.reviews.append((review_id, case_id, actor_id, note))
        self._remember_audit(actor_id, "ai_review", review_id)
        return review_id

    async def record_admin(self, *, actor_id: str, action: str, subject_id: str) -> AuditRecord:
        return self._remember_audit(actor_id, action, subject_id)

    def _remember_audit(self, actor_id: str, action: str, subject_id: str) -> AuditRecord:
        number = self._next("audit")
        record = AuditRecord(
            id=f"audit_{number}",
            actor_id=actor_id,
            action=action,
            subject_id=subject_id,
            created_at=self._clock.now(),
        )
        self.audit.append(record)
        return record
