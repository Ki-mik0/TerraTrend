"""Argon2 passwords and JWT sessions."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError


class ArgonPassword:
    def __init__(self) -> None:
        self._hasher = PasswordHasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerificationError:
            return False


DEV_SECRET = "earthtrend-dev-session-secret-key"
SESSION_TTL = 60 * 60  # an access token lives one hour
REFRESH_GRACE = 30 * 24 * 60 * 60  # an expired token may still be swapped for a new one for 30 days


class JwtTokens:
    """HS256 session tokens with an expiry. `SESSION_SECRET` sets the key; the dev key is only for local runs."""

    def __init__(self, secret: str | None = None, *, ttl: int = SESSION_TTL, grace: int = REFRESH_GRACE, clock: Callable[[], float] = time.time) -> None:
        self._secret = secret or os.environ.get("SESSION_SECRET") or DEV_SECRET
        self._ttl = ttl
        self._grace = grace
        self._clock = clock

    def issue(self, *, user_id: str, role: str) -> str:
        now = int(self._clock())
        return jwt.encode({"sub": user_id, "role": role, "iat": now, "exp": now + self._ttl}, self._secret, algorithm="HS256")

    def read(self, token: str) -> tuple[str, str]:
        """A live token's user and role; an expired or forged one raises."""
        payload = jwt.decode(token, self._secret, algorithms=["HS256"], options={"require": ["exp"], "verify_exp": False})
        if int(payload["exp"]) <= self._clock():
            raise jwt.ExpiredSignatureError("Signature has expired")
        return str(payload["sub"]), str(payload["role"])

    def refreshable(self, token: str) -> tuple[str, str]:
        """User and role of a genuine token that is live or expired less than the grace period ago."""
        payload = jwt.decode(token, self._secret, algorithms=["HS256"], options={"verify_exp": False})
        expires = payload.get("exp")
        if expires is not None and int(expires) + self._grace <= self._clock():
            raise jwt.ExpiredSignatureError("Refresh window has passed")
        return str(payload["sub"]), str(payload["role"])

    def expires_at(self, token: str) -> int:
        """Unix seconds when the token stops working."""
        payload = jwt.decode(token, self._secret, algorithms=["HS256"], options={"verify_exp": False})
        return int(payload.get("exp", 0))
