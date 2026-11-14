"""Education HTTP routes."""

from __future__ import annotations

from litestar import Request, Router, get, post
from litestar.exceptions import HTTPException
from litestar.params import FromPath, FromQuery, JSONBody

from earthtrend.api.api.education.schemas import (
    AssignmentRequest,
    AssignmentResponse,
    BadgeResponse,
    DemoProgressResponse,
    DemoResponse,
    DemoStepResponse,
    GlossaryResponse,
    LabRequest,
    LabResponse,
    Language,
    QuizAnswerRequest,
    QuizResponse,
    QuizResultResponse,
    SharedAssignmentResponse,
    ShareResponse,
    SubmissionRequest,
    SubmissionResponse,
)
from earthtrend.api.api.shared.auth import require_actor
from earthtrend.api.application.education.service import EducationService
from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.domain.catalog.model import DemoScenario
from earthtrend.api.domain.education.model import Assignment, EducationError, LabParams, Submission


def _http(error: EducationError) -> HTTPException:
    if error.code == "forbidden":
        status = 403
    elif error.code.startswith("invalid_"):
        status = 422
    elif error.code == "data_not_ready":
        status = 503
    else:
        status = 404
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message})


def _assignment(item: Assignment) -> AssignmentResponse:
    return AssignmentResponse(
        id=item.id,
        teacher_id=item.teacher_id,
        title=item.title,
        student_ids=list(item.student_ids),
        case_ids=list(item.case_ids),
        share_token=None if item.share is None else item.share.token,
    )


def _submission(item: Submission) -> SubmissionResponse:
    return SubmissionResponse(
        id=item.id,
        assignment_id=item.assignment_id,
        student_id=item.student_id,
        case_id=item.case_id,
        text=item.text,
        demo_id=item.demo_id,
    )


def _demo(item: DemoScenario) -> DemoResponse:
    return DemoResponse(
        id=item.id,
        title=item.title,
        language=item.language,
        summary=item.summary,
        tool=item.tool,
        variable_id=item.variable_id,
        region_id=item.region_id,
        period_start=item.period_start,
        period_end=item.period_end,
        steps=[
            DemoStepResponse(number=index, title=step.title, text=step.text, target=step.target)
            for index, step in enumerate(item.steps, start=1)
        ],
    )


def education_router(service: EducationService, identity: IdentityService) -> Router:
    @get("/education/assignments")
    async def list_assignments(request: Request) -> list[AssignmentResponse]:
        actor = await require_actor(request, identity)
        items = await service.list_assignments(actor_id=actor.id, role=actor.role)
        return [_assignment(item) for item in items]

    @post("/education/assignments")
    async def create_assignment(data: JSONBody[AssignmentRequest], request: Request) -> AssignmentResponse:
        actor = await require_actor(request, identity)
        try:
            created = await service.create_assignment(
                teacher_id=actor.id,
                role=actor.role,
                title=data.title,
                student_ids=data.student_ids,
                case_ids=data.case_ids,
            )
        except EducationError as error:
            raise _http(error) from error
        return _assignment(created)

    @get("/education/assignments/{assignment_id:str}")
    async def get_assignment(assignment_id: FromPath[str], request: Request) -> AssignmentResponse:
        actor = await require_actor(request, identity)
        try:
            found = await service.get_assignment(assignment_id, actor_id=actor.id, role=actor.role)
        except EducationError as error:
            raise _http(error) from error
        return _assignment(found)

    @post("/education/assignments/{assignment_id:str}/share")
    async def share_assignment(assignment_id: FromPath[str], request: Request) -> ShareResponse:
        actor = await require_actor(request, identity)
        try:
            link = await service.share(assignment_id, actor_id=actor.id, role=actor.role)
        except EducationError as error:
            raise _http(error) from error
        return ShareResponse(token=link.token)

    @get("/education/shared/{token:str}")
    async def open_shared(token: FromPath[str], request: Request) -> SharedAssignmentResponse:
        actor = await require_actor(request, identity)
        try:
            found = await service.open_shared(token)
        except EducationError as error:
            raise _http(error) from error
        return SharedAssignmentResponse(
            id=found.id, title=found.title, case_ids=list(found.case_ids), joined=actor.id in found.student_ids
        )

    @post("/education/shared/{token:str}/join")
    async def join_shared(token: FromPath[str], request: Request) -> SharedAssignmentResponse:
        actor = await require_actor(request, identity)
        try:
            found = await service.join_shared(token, actor_id=actor.id, role=actor.role)
        except EducationError as error:
            raise _http(error) from error
        return SharedAssignmentResponse(
            id=found.id, title=found.title, case_ids=list(found.case_ids), joined=actor.id in found.student_ids
        )

    @post("/education/submissions")
    async def submit(data: JSONBody[SubmissionRequest], request: Request) -> SubmissionResponse:
        actor = await require_actor(request, identity)
        try:
            created = await service.submit(
                assignment_id=data.assignment_id,
                student_id=actor.id,
                case_id=data.case_id,
                text=data.text,
                demo_id=data.demo_id,
            )
        except EducationError as error:
            raise _http(error) from error
        return _submission(created)

    @get("/education/submissions")
    async def list_submissions(request: Request, assignment_id: FromQuery[str | None] = None) -> list[SubmissionResponse]:
        actor = await require_actor(request, identity)
        try:
            items = await service.list_submissions(actor_id=actor.id, role=actor.role, assignment_id=assignment_id)
        except EducationError as error:
            raise _http(error) from error
        return [_submission(item) for item in items]

    @get("/education/badges")
    async def list_badges(request: Request) -> list[BadgeResponse]:
        actor = await require_actor(request, identity)
        badges = await service.list_badges(user_id=actor.id)
        return [
            BadgeResponse(id=item.id, user_id=item.user_id, code=item.code, reason=item.reason) for item in badges
        ]

    @get("/education/demos")
    async def list_demos(request: Request, lang: FromQuery[Language] = "uk") -> list[DemoResponse]:
        await require_actor(request, identity)
        return [_demo(item) for item in await service.list_demos(lang)]

    @get("/education/demos/{demo_id:str}")
    async def get_demo(demo_id: FromPath[str], request: Request, lang: FromQuery[Language] = "uk") -> DemoResponse:
        await require_actor(request, identity)
        try:
            return _demo(await service.get_demo(demo_id, lang))
        except EducationError as error:
            raise _http(error) from error

    @post("/education/demos/{demo_id:str}/steps/{step:int}")
    async def complete_step(demo_id: FromPath[str], step: FromPath[int], request: Request) -> DemoProgressResponse:
        actor = await require_actor(request, identity)
        try:
            demo = await service.get_demo(demo_id)
            progress, badge = await service.complete_demo_step(demo_id, step, user_id=actor.id)
        except EducationError as error:
            raise _http(error) from error
        total = len(demo.steps)
        return DemoProgressResponse(
            demo_id=demo_id,
            steps_done=sorted(progress.steps_done),
            total_steps=total,
            finished=progress.finished(total),
            badge=None if badge is None else badge.code,
        )

    @get("/education/glossary")
    async def list_glossary(request: Request, lang: FromQuery[Language] = "uk") -> list[GlossaryResponse]:
        await require_actor(request, identity)
        return [
            GlossaryResponse(
                id=item.id,
                term=item.term,
                text=item.text,
                language=item.language,
                example=item.example,
                kind="page" if item.kind == "page" else "term",
            )
            for item in await service.list_glossary(lang)
        ]

    @get("/education/quizzes")
    async def list_quizzes(request: Request, lang: FromQuery[Language] = "uk") -> list[QuizResponse]:
        await require_actor(request, identity)
        return [QuizResponse(**item) for item in await service.list_quizzes(lang)]

    @post("/education/quizzes/{quiz_id:str}")
    async def answer_quiz(
        quiz_id: FromPath[str], data: JSONBody[QuizAnswerRequest], request: Request
    ) -> QuizResultResponse:
        actor = await require_actor(request, identity)
        try:
            result = await service.submit_quiz(quiz_id, data.choice, user_id=actor.id)
        except EducationError as error:
            raise _http(error) from error
        return QuizResultResponse(
            quiz_id=result.quiz_id, correct=result.correct, explanation=result.explanation, badge=result.badge
        )

    @post("/education/lab")
    async def run_lab(data: JSONBody[LabRequest], request: Request) -> LabResponse:
        await require_actor(request, identity)
        try:
            run = await service.run_lab(LabParams(**data.model_dump()))
        except EducationError as error:
            raise _http(error) from error
        return LabResponse(
            status=run.status,
            **data.model_dump(),
            slope_decade=run.slope_decade,
            p_value=run.p_value,
            n_eff=run.n_eff,
            significant=run.significant,
            series=list(run.series),
        )

    return Router(
        path="/api/v1",
        route_handlers=[
            list_assignments,
            create_assignment,
            get_assignment,
            share_assignment,
            open_shared,
            join_shared,
            submit,
            list_submissions,
            list_badges,
            list_demos,
            get_demo,
            complete_step,
            list_glossary,
            list_quizzes,
            answer_quiz,
            run_lab,
        ],
    )
