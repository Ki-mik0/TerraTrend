"""Education use cases. Lessons come from the catalog; static reads go through the cache."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from earthtrend.api.application.education.ports import (
    CaseLinkPort,
    CaseLookup,
    EducationStore,
    LabPort,
    LessonPort,
    QuizBank,
)
from earthtrend.api.application.shared.cache import CachePort
from earthtrend.api.domain.cases.model import Case
from earthtrend.api.domain.catalog.model import DemoScenario, DemoStep, GlossaryEntry
from earthtrend.api.domain.education.model import (
    Assignment,
    Badge,
    DemoProgress,
    EducationError,
    LabParams,
    LabRun,
    Quiz,
    QuizResult,
    ShareLink,
    Submission,
    badges_for_case,
    require_language,
    require_teacher,
)

LESSON_TTL = 24 * 3600
LAB_TTL = 24 * 3600
BADGE_TTL = 10 * 60
SHARE_TTL = 3600


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _demo_from(raw: dict[str, Any]) -> DemoScenario:
    steps = tuple(DemoStep(**step) for step in raw.pop("steps"))
    return DemoScenario(**raw, steps=steps)


def _quiz_public(quiz: Quiz) -> dict[str, Any]:
    """A quiz as the client sees it: no answer, no explanation."""
    return {"id": quiz.id, "language": quiz.language, "question": quiz.question, "options": list(quiz.options)}


class EducationService:
    def __init__(
        self,
        *,
        lessons: LessonPort,
        store: EducationStore,
        quizzes: QuizBank,
        lab: LabPort,
        cache: CachePort,
        cases: CaseLookup | None = None,
        links: CaseLinkPort | None = None,
        ids: Callable[[str], str] = _new_id,
    ) -> None:
        self._lessons = lessons
        self._store = store
        self._quizzes = quizzes
        self._lab = lab
        self._cache = cache
        self._cases = cases
        self._links = links
        self._ids = ids

    # Assignments -----------------------------------------------------------------------------

    async def list_assignments(self, *, actor_id: str, role: str) -> list[Assignment]:
        items = await self._store.list_assignments(None if role == "admin" else actor_id)
        return [item for item in items if item.visible_to(actor_id, role)]

    async def create_assignment(
        self,
        *,
        teacher_id: str,
        role: str,
        title: str,
        student_ids: list[str],
        case_ids: list[str],
    ) -> Assignment:
        require_teacher(role)
        if not title.strip():
            raise EducationError("invalid_assignment", "Завданню потрібна назва")
        assignment = Assignment(
            id=self._ids("asg"),
            teacher_id=teacher_id,
            title=title.strip(),
            student_ids=tuple(dict.fromkeys(student_ids)),
            case_ids=tuple(dict.fromkeys(case_ids)),
        )
        await self._store.save_assignment(assignment)
        if self._links is not None:
            for case_id in assignment.case_ids:
                await self._links.link(case_id)
        return assignment

    async def get_assignment(self, assignment_id: str, *, actor_id: str, role: str) -> Assignment:
        assignment = await self._store.get_assignment(assignment_id)
        if assignment is None or not assignment.visible_to(actor_id, role):
            raise EducationError("assignment_not_found", "Завдання не знайдено")
        return assignment

    async def share(self, assignment_id: str, *, actor_id: str, role: str) -> ShareLink:
        require_teacher(role)
        assignment = await self.get_assignment(assignment_id, actor_id=actor_id, role=role)
        if not assignment.owned_by(actor_id, role):
            raise EducationError("forbidden", "Посилання видає автор завдання")
        if assignment.share is not None:
            await self._cache.delete(f"edu:share:{assignment.share.token}")
        assignment.share = ShareLink(token=secrets.token_urlsafe(16))
        await self._store.save_assignment(assignment)
        return assignment.share

    async def open_shared(self, token: str) -> Assignment:
        """Resolve a class link. The token is the secret, so any signed-in actor may read the title."""
        key = f"edu:share:{token}"
        cached_id = await self._cache.get_json(key)
        assignment = None
        if cached_id is not None:
            assignment = await self._store.get_assignment(cached_id)
        if assignment is None or assignment.share is None or assignment.share.token != token:
            assignment = await self._store.find_by_token(token)
            if assignment is None:
                raise EducationError("share_not_found", "Посилання недійсне")
            await self._cache.set_json(key, assignment.id, SHARE_TTL)
        return assignment

    async def join_shared(self, token: str, *, actor_id: str, role: str) -> Assignment:
        assignment = await self.open_shared(token)
        if assignment.join(actor_id, role):
            await self._store.save_assignment(assignment)
        return assignment

    async def submit(
        self,
        *,
        assignment_id: str,
        student_id: str,
        case_id: str,
        text: str,
        demo_id: str | None,
    ) -> Submission:
        assignment = await self._store.get_assignment(assignment_id)
        if assignment is None or student_id not in assignment.student_ids:
            raise EducationError("assignment_not_found", "Завдання не знайдено")
        if not text.strip():
            raise EducationError("invalid_submission", "Відповідь не може бути порожньою")
        if self._cases is not None:
            case = await self._cases.get(case_id)
            if case is None:
                raise EducationError("case_not_found", "Справу не знайдено")
            if not assignment.accepts_case(case_id, case.owner_id, student_id):
                raise EducationError("forbidden", "Ця справа не належить завданню")
        elif case_id not in assignment.case_ids and assignment.case_ids:
            raise EducationError("forbidden", "Ця справа не належить завданню")
        if demo_id and demo_id not in {item.id for item in await self._lessons.list_demos()}:
            raise EducationError("demo_not_found", "Демо не знайдено")
        submission = Submission(
            id=self._ids("sub"),
            assignment_id=assignment.id,
            student_id=student_id,
            case_id=case_id,
            text=text,
            demo_id=demo_id,
        )
        await self._store.add_submission(submission)
        await self.award(student_id, "assignment", assignment.id)
        return submission

    async def list_submissions(
        self, *, actor_id: str, role: str, assignment_id: str | None = None
    ) -> list[Submission]:
        require_teacher(role)
        if assignment_id is not None:
            assignment = await self.get_assignment(assignment_id, actor_id=actor_id, role=role)
            if not assignment.owned_by(actor_id, role):
                raise EducationError("forbidden", "Відповіді бачить автор завдання")
            return await self._store.list_submissions([assignment.id])
        owned = await self._store.list_assignments(None if role == "admin" else actor_id)
        ids = [item.id for item in owned if item.owned_by(actor_id, role)]
        return await self._store.list_submissions(ids)

    # Badges ----------------------------------------------------------------------------------

    async def award(self, user_id: str, code: str, reason: str) -> Badge | None:
        """Award a badge once. Every award path goes through here, never through a controller."""
        badge = Badge(id=self._ids("badge"), user_id=user_id, code=code, reason=reason)
        if not await self._store.add_badge(badge):
            return None
        await self._cache.delete(f"edu:badges:{user_id}")
        return badge

    async def list_badges(self, *, user_id: str) -> list[Badge]:
        key = f"edu:badges:{user_id}"
        cached = await self._cache.get_json(key)
        if cached is not None:
            return [Badge(**item) for item in cached]
        badges = await self._store.list_badges(user_id)
        await self._cache.set_json(key, [asdict(item) for item in badges], BADGE_TTL)
        return badges

    async def case_completed(self, case: Case) -> list[Badge]:
        """Badges for a finished case. Guests and temporary cases earn nothing."""
        if case.status != "completed" or case.verdict is None or case.role == "guest" or case.ephemeral:
            return []
        series = case.series
        alibi = None if case.evidence is None else case.evidence.alibi
        codes = badges_for_case(
            verdict_code=case.verdict.code,
            split_flag=series is not None and series.split.split_flag,
            b_raw=0.0 if alibi is None else alibi.b_raw,
            b_adjusted=0.0 if alibi is None else alibi.b_adjusted,
            influential_year=None if series is None else series.jackknife.influential_year,
        )
        earned = [await self.award(case.owner_id, code, case.id) for code in codes]
        return [item for item in earned if item is not None]

    # Demos and glossary ----------------------------------------------------------------------

    async def list_demos(self, language: str = "uk") -> list[DemoScenario]:
        require_language(language)
        key = f"edu:demos:{await self._lessons.lessons_version()}:{language}"
        cached = await self._cache.get_json(key)
        if cached is not None:
            return [_demo_from(item) for item in cached]
        demos = await self._lessons.list_demos(language)
        await self._cache.set_json(key, [asdict(item) for item in demos], LESSON_TTL)
        return demos

    async def get_demo(self, demo_id: str, language: str = "uk") -> DemoScenario:
        for demo in await self.list_demos(language):
            if demo.id == demo_id:
                return demo
        raise EducationError("demo_not_found", "Демо не знайдено")

    async def demo_progress(self, demo_id: str, *, user_id: str) -> tuple[DemoScenario, DemoProgress]:
        """The steps this user already finished in a demo. A demo never opened has none."""
        demo = await self.get_demo(demo_id)
        progress = await self._store.get_progress(user_id, demo_id) or DemoProgress(user_id=user_id, demo_id=demo_id)
        return demo, progress

    async def complete_demo_step(self, demo_id: str, step: int, *, user_id: str) -> tuple[DemoProgress, Badge | None]:
        demo = await self.get_demo(demo_id)
        progress = await self._store.get_progress(user_id, demo_id) or DemoProgress(user_id=user_id, demo_id=demo_id)
        finished_now = progress.complete_step(step, len(demo.steps))
        await self._store.save_progress(progress)
        badge = await self.award(user_id, "demo", demo_id) if finished_now else None
        return progress, badge

    async def list_glossary(self, language: str = "uk") -> list[GlossaryEntry]:
        require_language(language)
        key = f"edu:glossary:{await self._lessons.lessons_version()}:{language}"
        cached = await self._cache.get_json(key)
        if cached is not None:
            return [GlossaryEntry(**item) for item in cached]
        entries = await self._lessons.list_glossary(language)
        await self._cache.set_json(key, [asdict(item) for item in entries], LESSON_TTL)
        return entries

    # Quizzes ---------------------------------------------------------------------------------

    async def list_quizzes(self, language: str = "uk") -> list[dict[str, Any]]:
        require_language(language)
        key = f"edu:quizzes:{self._quizzes.version}:{language}"
        cached = await self._cache.get_json(key)
        if cached is not None:
            return cached
        public = [_quiz_public(item) for item in await self._quizzes.list(language)]
        await self._cache.set_json(key, public, LESSON_TTL)
        return public

    async def submit_quiz(self, quiz_id: str, choice: int, *, user_id: str) -> QuizResult:
        quiz = await self._quizzes.get(quiz_id)
        if quiz is None:
            raise EducationError("quiz_not_found", "Вікторину не знайдено")
        correct = quiz.check(choice)
        await self._store.record_quiz(user_id=user_id, quiz_id=quiz_id, correct=correct)
        badge = await self.award(user_id, quiz.badge_code, quiz.id) if correct else None
        return QuizResult(
            quiz_id=quiz.id,
            correct=correct,
            explanation=quiz.explanation,
            badge=None if badge is None else badge.code,
        )

    # Lab -------------------------------------------------------------------------------------

    async def run_lab(self, params: LabParams) -> LabRun:
        key = "edu:lab:" + hashlib.sha256(json.dumps(asdict(params), sort_keys=True).encode()).hexdigest()
        cached = await self._cache.get_json(key)
        if cached is not None:
            cached["params"] = LabParams(**cached["params"])
            cached["series"] = tuple(cached["series"])
            return LabRun(**cached)
        run = await self._lab.run(params)
        if not run.ready:
            raise EducationError("data_not_ready", "Лабораторія ще не підключена до аналітики")
        await self._cache.set_json(key, asdict(run), LAB_TTL)
        return run
