"""Education HTTP schemas."""

from typing import Literal

from pydantic import BaseModel, Field

Language = Literal["uk", "en"]


class AssignmentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    student_ids: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)


class AssignmentResponse(BaseModel):
    id: str
    teacher_id: str
    title: str
    student_ids: list[str]
    case_ids: list[str]
    share_token: str | None = None


class SharedAssignmentResponse(BaseModel):
    """What a class link reveals before and after joining: no roster, no answers."""

    id: str
    title: str
    case_ids: list[str]
    joined: bool


class ShareResponse(BaseModel):
    token: str


class SubmissionRequest(BaseModel):
    assignment_id: str
    case_id: str
    text: str = Field(min_length=1, max_length=5000)
    demo_id: str | None = None


class SubmissionResponse(BaseModel):
    id: str
    assignment_id: str
    student_id: str
    case_id: str
    text: str
    demo_id: str | None


class BadgeResponse(BaseModel):
    id: str
    user_id: str
    code: str
    reason: str


class DemoStepResponse(BaseModel):
    number: int
    title: str
    text: str
    target: str


class DemoResponse(BaseModel):
    id: str
    title: str
    language: str
    summary: str
    tool: str
    variable_id: str
    region_id: str
    period_start: str
    period_end: str
    steps: list[DemoStepResponse]


class DemoProgressResponse(BaseModel):
    demo_id: str
    steps_done: list[int]
    total_steps: int
    finished: bool
    badge: str | None = None


class GlossaryResponse(BaseModel):
    id: str
    term: str
    text: str
    language: str
    example: str
    kind: Literal["term", "page"]


class QuizResponse(BaseModel):
    id: str
    language: str
    question: str
    options: list[str]


class QuizAnswerRequest(BaseModel):
    choice: int = Field(ge=0)


class QuizResultResponse(BaseModel):
    quiz_id: str
    correct: bool
    explanation: str
    badge: str | None = None


class LabRequest(BaseModel):
    noise: float = Field(ge=0, le=10)
    years: int = Field(ge=5, le=100)
    autocorrelation: float = Field(ge=0, lt=0.95)
    trend_per_decade: float = 0.2
    seed: int = 0


class LabResponse(BaseModel):
    status: str
    noise: float
    years: int
    autocorrelation: float
    trend_per_decade: float
    seed: int
    slope_decade: float | None = None
    p_value: float | None = None
    n_eff: float | None = None
    significant: bool | None = None
    series: list[float] = Field(default_factory=list)
