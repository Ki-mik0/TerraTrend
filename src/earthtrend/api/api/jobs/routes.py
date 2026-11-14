"""Job HTTP routes. The event stream reads the job itself."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from litestar import Request, Router, delete, get
from litestar.exceptions import HTTPException
from litestar.params import FromPath
from litestar.response.sse import ServerSentEvent, ServerSentEventMessage

from earthtrend.api.api.jobs.schemas import JobResponse
from earthtrend.api.api.shared.auth import require_admin, require_actor
from earthtrend.api.application.identity.service import IdentityService
from earthtrend.api.application.jobs.service import JobService
from earthtrend.api.domain.jobs.model import Job, JobError


def _http(error: JobError) -> HTTPException:
    status = 403 if error.code == "forbidden" else 404
    if error.code == "cancel_not_allowed":
        status = 409
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message})


def _body(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        case_id=job.case_id,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        message=job.message,
    )


def jobs_router(service: JobService, identity: IdentityService) -> Router:
    @get("/jobs/{job_id:str}")
    async def get_job(job_id: FromPath[str], request: Request) -> JobResponse:
        actor = await require_actor(request, identity)
        try:
            job = await service.get(job_id, actor_id=actor.id, role=actor.role)
        except JobError as error:
            raise _http(error) from error
        return _body(job)

    @get("/jobs/{job_id:str}/events")
    async def job_events(job_id: FromPath[str], request: Request) -> ServerSentEvent:
        actor = await require_actor(request, identity)
        try:
            job = await service.get(job_id, actor_id=actor.id, role=actor.role)
        except JobError as error:
            raise _http(error) from error

        async def messages() -> AsyncIterator[ServerSentEventMessage]:
            async for event in service.stream(job_id, actor_id=actor.id, role=actor.role):
                yield ServerSentEventMessage(
                    event=event["event"],
                    data=json.dumps(event["data"], ensure_ascii=False),
                )

        return ServerSentEvent(messages())

    @delete("/jobs/{job_id:str}", status_code=204)
    async def cancel_job(job_id: FromPath[str], request: Request) -> None:
        actor = await require_actor(request, identity)
        try:
            await service.cancel(job_id, actor_id=actor.id, role=actor.role)
        except JobError as error:
            raise _http(error) from error

    @get("/admin/jobs")
    async def list_jobs(request: Request) -> list[JobResponse]:
        actor = await require_actor(request, identity)
        require_admin(actor)
        try:
            jobs = await service.list_all(role=actor.role)
        except JobError as error:
            raise _http(error) from error
        return [_body(job) for job in jobs]

    return Router(path="/api/v1", route_handlers=[get_job, job_events, cancel_job, list_jobs])
