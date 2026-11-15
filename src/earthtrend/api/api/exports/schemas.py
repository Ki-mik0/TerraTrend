"""Export HTTP schemas."""

from typing import Literal

from pydantic import BaseModel

ExportFormat = Literal[
    "csv",
    "geojson",
    "ipynb",
    "html",
    "png",
    "pdf",
    "zip",
    "nc",
    "svg",
    "citation",
]


class ExportRequest(BaseModel):
    format: ExportFormat
    language: Literal["uk", "en"] | None = None


class ExportResponse(BaseModel):
    id: str
    case_id: str
    format: str
    status: str
    download_url: str | None = None
    filename: str | None = None
