"""Map tile routes. Public: the map works for a guest."""

from __future__ import annotations

import re

from litestar import Request, Router, get, post
from litestar.exceptions import HTTPException
from litestar.params import FromPath, FromQuery, JSONBody
from litestar.response import Response

from earthtrend.api.api.tiles.schemas import GridProductResponse
from earthtrend.api.application.tiles.service import TileService
from earthtrend.api.domain.tiles.model import PALETTES, PRODUCTS, TileError, TileRequest

CACHE_CONTROL = "public, max-age=86400, immutable"
_Y_PNG = re.compile(r"^(\d{1,5})\.png$")
_STATUS = {
    "tile_out_of_range": 422,
    "palette_invalid": 422,
    "product_invalid": 422,
    "season_invalid": 422,
    "period_invalid": 422,
    "year_invalid": 422,
    "grid_not_found": 404,
    "variable_not_found": 404,
}


def _http(error: TileError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS.get(error.code, 422), detail={"code": error.code, "message": error.message}
    )


def _not_modified(request: Request, etag: str) -> bool:
    sent = request.headers.get("if-none-match", "")
    return etag in {tag.strip() for tag in sent.split(",")}


def tiles_router(service: TileService) -> Router:
    @get(
        "/tiles/{product:str}/{z:int}/{x:int}/{y_png:str}",
        media_type="image/png",
        summary="Map tile PNG",
        description="Path ends with `{y}.png`. Products: `trend`, `ai_class`.",
    )
    async def get_tile(
        request: Request,
        product: FromPath[str],
        z: FromPath[int],
        x: FromPath[int],
        y_png: FromPath[str],
        variable_id: FromQuery[str],
        period: FromQuery[str],
        season: FromQuery[str] = "annual",
        palette: FromQuery[str] = "rdbu",
        significant_only: FromQuery[bool] = False,
        year: FromQuery[int | None] = None,
    ) -> Response[bytes]:
        match = _Y_PNG.match(y_png)
        if match is None:
            raise HTTPException(
                status_code=404, detail={"code": "tile_not_found", "message": "Тайл має закінчуватися на .png"}
            )
        try:
            tile_request = TileRequest(
                product=product,
                z=z,
                x=x,
                y=int(match.group(1)),
                variable_id=variable_id,
                period=period,
                season=season,
                palette=palette,
                significant_only=significant_only,
                year=year,
            )
            etag = await service.etag_for(tile_request)
            headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
            if _not_modified(request, etag):
                return Response(content=b"", status_code=304, headers=headers, media_type="image/png")
            result = await service.tile(tile_request)
        except TileError as error:
            raise _http(error) from error
        return Response(
            content=result.data,
            media_type="image/png",
            headers={**headers, "X-Tile-Cache": result.outcome},
        )

    @get("/tiles/products")
    async def list_products(variable_id: FromQuery[str | None] = None) -> list[GridProductResponse]:
        items = await service.products(variable_id)
        return [
            GridProductResponse(
                variable_id=item.variable_id,
                period=item.period,
                season=item.season,
                data_version=item.version,
                bbox=list(item.bbox),
                resolution=item.resolution,
                vmax=item.vmax,
                frame_vmax=item.frame_vmax,
                years=list(item.years),
                products=sorted(PRODUCTS),
                palettes=sorted(PALETTES),
                tile_url=(
                    "/api/v1/tiles/{product}/{z}/{x}/{y}.png"
                    f"?variable_id={item.variable_id}&period={item.period}&season={item.season}"
                ),
            )
            for item in items
        ]

    @post("/tiles/products", status_code=201)
    async def compute_product(data: JSONBody[dict]) -> GridProductResponse:
        from earthtrend.api.infrastructure.analytics_bridge import grid_product, run_blocking

        product = await run_blocking(grid_product, data)
        saved = await service._grids.save_analyzed(
            variable_id=data["variable_id"],
            period=data["period"],
            season=data.get("season", "annual"),
            product=product,
        )
        return GridProductResponse(
            variable_id=saved.variable_id,
            period=saved.period,
            season=saved.season,
            data_version=saved.version,
            bbox=list(saved.bbox),
            resolution=saved.resolution,
            vmax=saved.vmax,
            years=list(saved.years),
            products=sorted(PRODUCTS),
            palettes=sorted(PALETTES),
            tile_url="",
        )

    return Router(path="/api/v1", route_handlers=[get_tile, list_products, compute_product])
