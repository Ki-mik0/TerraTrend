"""Shared cache port. Values are JSON; a miss and a cache outage look the same.

Keys start with a family (`edu:`, `radar:`, `story:`, `case:` ...). Admins clear a cache by family.
"""

from __future__ import annotations

from typing import Any, Protocol


class CachePort(Protocol):
    async def get_json(self, key: str) -> Any | None: ...

    async def set_json(self, key: str, value: Any, ttl: int) -> None: ...

    async def delete(self, *keys: str) -> None: ...


class AdminCachePort(CachePort, Protocol):
    """What the cache admin needs on top of reads and writes."""

    async def delete_prefix(self, prefix: str) -> int: ...

    async def ping(self) -> bool: ...
