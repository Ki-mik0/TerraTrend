"""Argon2 passwords and JWT sessions."""

from __future__ import annotations

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


class JwtTokens:
    def __init__(self, secret: str = "earthtrend-dev-session-secret-key") -> None:
        self._secret = secret

    def issue(self, *, user_id: str, role: str) -> str:
        return jwt.encode({"sub": user_id, "role": role}, self._secret, algorithm="HS256")

    def read(self, token: str) -> tuple[str, str]:
        payload = jwt.decode(token, self._secret, algorithms=["HS256"])
        return str(payload["sub"]), str(payload["role"])
