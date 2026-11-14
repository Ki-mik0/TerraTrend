"""Run the heavy step outside the event loop."""

from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor

from earthtrend.api.infrastructure.jobs.pool import execute_heavy


class ProcessPoolRunner:
    def __init__(self) -> None:
        self._pool: ProcessPoolExecutor | None = None

    async def run(self, case_id: str) -> None:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=2)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._pool, execute_heavy, case_id)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None
