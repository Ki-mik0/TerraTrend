"""Story HTTP schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from earthtrend.api.domain.story.model import Story


class StoryRequest(BaseModel):
    variable_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    language: Literal["uk", "en"] = "uk"


class RelatedResponse(BaseModel):
    variable_id: str
    name: str
    role: str
    lag_months: int
    partial_r: float | None = None


class PaperResponse(BaseModel):
    title: str
    url: str
    doi: str


class StoryResponse(BaseModel):
    id: str
    language: str
    title: str
    text: str
    case_id: str | None = None
    cached: bool
    source: str
    slope_decade: float
    direction: str
    pattern: str
    related: list[RelatedResponse]
    papers: list[PaperResponse]
    caveats: list[str]
    versions: dict[str, str]
    warnings: list[str]


def story_response(story: Story) -> StoryResponse:
    facts = story.facts
    return StoryResponse(
        id=story.id,
        language=story.language,
        title=story.title,
        text=story.text,
        case_id=story.case_id,
        cached=story.cached,
        source=story.source,
        slope_decade=facts.slope_decade,
        direction=facts.direction,
        pattern=facts.pattern,
        related=[
            RelatedResponse(
                variable_id=item.variable_id,
                name=item.name or item.variable_id,
                role=item.role,
                lag_months=item.lag_months,
                partial_r=item.partial_r,
            )
            for item in facts.related
        ],
        papers=[PaperResponse(title=paper.title, url=paper.url, doi=paper.doi) for paper in facts.papers],
        caveats=list(story.caveats),
        versions=dict(facts.versions),
        warnings=list(story.warnings),
    )
