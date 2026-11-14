"""CMR registration runs outside the request process. It does not call NASA."""

from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor


def prepare_cmr(query: str) -> str:
    text = query.strip()
    if not text:
        raise ValueError("empty")
    cleaned = "".join(char if char.isalnum() else "_" for char in text.casefold())
    compact = "_".join(part for part in cleaned.split("_") if part)
    return compact[:64] or "cmr_item"


class ProcessCmr:
    def __init__(self) -> None:
        self._pool: ProcessPoolExecutor | None = None

    async def run(self, query: str) -> str:
        loop = asyncio.get_running_loop()
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=1)
        return await loop.run_in_executor(self._pool, prepare_cmr, query)
