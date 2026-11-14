"""Ports of the education zone."""

from __future__ import annotations

from typing import Protocol

from earthtrend.api.domain.cases.model import Case
from earthtrend.api.domain.catalog.model import DemoScenario, GlossaryEntry
from earthtrend.api.domain.education.model import (
    Assignment,
    Badge,
    DemoProgress,
    LabParams,
    LabRun,
    Quiz,
    Submission,
)


class LessonPort(Protocol):
    """Demos and the glossary live in the catalog."""

    async def list_demos(self, language: str | None = None) -> list[DemoScenario]: ...

    async def list_glossary(self, language: str | None = None) -> list[GlossaryEntry]: ...

    async def lessons_version(self) -> int: ...


class CaseLinkPort(Protocol):
    async def link(self, case_id: str) -> None: ...


class CaseLookup(Protocol):
    async def get(self, case_id: str) -> Case | None: ...


class QuizBank(Protocol):
    version: str

    async def list(self, language: str) -> list[Quiz]: ...

    async def get(self, quiz_id: str) -> Quiz | None: ...


class LabPort(Protocol):
    """The statistics lab simulator. Analytics owns the real calculation."""

    async def run(self, params: LabParams) -> LabRun: ...


class EducationStore(Protocol):
    async def save_assignment(self, assignment: Assignment) -> None: ...

    async def get_assignment(self, assignment_id: str) -> Assignment | None: ...

    async def find_by_token(self, token: str) -> Assignment | None: ...

    async def list_assignments(self, actor_id: str | None) -> list[Assignment]:
        """Assignments the actor teaches or is enrolled in; `None` lists all of them."""
        ...

    async def add_submission(self, submission: Submission) -> None: ...

    async def list_submissions(self, assignment_ids: list[str]) -> list[Submission]: ...

    async def add_badge(self, badge: Badge) -> bool:
        """Store a badge; return False when the user already holds it."""
        ...

    async def list_badges(self, user_id: str) -> list[Badge]: ...

    async def get_progress(self, user_id: str, demo_id: str) -> DemoProgress | None: ...

    async def save_progress(self, progress: DemoProgress) -> None: ...

    async def record_quiz(self, *, user_id: str, quiz_id: str, correct: bool) -> None: ...
