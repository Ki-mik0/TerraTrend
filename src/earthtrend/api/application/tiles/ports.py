"""Ports of the tiles zone."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from earthtrend.api.domain.tiles.model import GridProduct, TileRequest


@dataclass(frozen=True)
class GridArrays:
    """Rows go north to south, columns west to east. `values` is the slope or the frame anomaly."""

    values: Any
    sig_fdr: Any
    ai_class: Any


class GridPort(Protocol):
    async def version(self) -> str: ...

    async def find(self, variable_id: str, period: str, season: str) -> GridProduct | None: ...

    async def products(self, variable_id: str | None = None) -> list[GridProduct]: ...

    async def arrays(self, product: GridProduct, year: int | None) -> GridArrays: ...


class TileRenderer(Protocol):
    def render(self, request: TileRequest, product: GridProduct, arrays: GridArrays) -> bytes: ...

    def empty(self) -> bytes: ...


class ObjectStorage(Protocol):
    async def get(self, key: str) -> bytes | None: ...

    async def put(self, key: str, data: bytes) -> None: ...


class VariableCheck(Protocol):
    async def get_variable(self, variable_id: str) -> object: ...
