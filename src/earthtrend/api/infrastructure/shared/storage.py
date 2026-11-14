"""Local object storage for rendered tiles and other bytes. Keys are relative POSIX paths."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath


class StorageError(Exception):
    pass


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        parts = PurePosixPath(key).parts
        if not parts or key.startswith("/") or "//" in key or "\\" in key or any(part in ("..", ".") for part in parts):
            raise StorageError(f"unsafe storage key: {key!r}")
        return self.root.joinpath(*parts)

    async def get(self, key: str) -> bytes | None:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            return None

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._write, self._path(key), data)

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(data)
            os.replace(temp, path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise

    async def delete_prefix(self, prefix: str) -> int:
        target = self._path(prefix.rstrip("/"))
        if not target.exists():
            return 0

        def remove() -> int:
            if target.is_file():
                target.unlink()
                return 1
            count = sum(1 for item in target.rglob("*") if item.is_file())
            shutil.rmtree(target)
            return count

        return await asyncio.to_thread(remove)

    async def ping(self) -> bool:
        probe = "health/.probe"
        try:
            await self.put(probe, b"ok")
            return await self.get(probe) == b"ok"
        except OSError:
            return False
