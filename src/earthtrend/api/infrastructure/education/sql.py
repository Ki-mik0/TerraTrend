"""Education tables on SQLAlchemy. Plain portable SQL: PostgreSQL in deployments, SQLite in tests."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from earthtrend.api.domain.education.model import (
    Assignment,
    Badge,
    DemoProgress,
    ShareLink,
    Submission,
    badge_key,
)


class Base(DeclarativeBase):
    pass


class AssignmentRow(Base):
    __tablename__ = "assignments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    teacher_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)


class AssignmentStudentRow(Base):
    __tablename__ = "assignment_students"

    assignment_id: Mapped[str] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), primary_key=True
    )
    student_id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class AssignmentCaseRow(Base):
    __tablename__ = "assignment_cases"

    assignment_id: Mapped[str] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), primary_key=True
    )
    case_id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class SubmissionRow(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[str] = mapped_column(String(64), nullable=False)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    demo_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class BadgeRow(Base):
    __tablename__ = "badges"
    __table_args__ = (UniqueConstraint("user_id", "code", "unique_reason", name="badges_once"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    unique_reason: Mapped[str] = mapped_column(String(64), nullable=False)


class QuizAttemptRow(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quiz_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)


class DemoProgressRow(Base):
    __tablename__ = "demo_progress"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    demo_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    steps: Mapped[str] = mapped_column(Text, nullable=False)


def _submission(row: SubmissionRow) -> Submission:
    return Submission(
        id=row.id,
        assignment_id=row.assignment_id,
        student_id=row.student_id,
        case_id=row.case_id,
        text=row.text,
        demo_id=row.demo_id,
    )


class SqlEducationStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def save_assignment(self, assignment: Assignment) -> None:
        async with self._sessions() as session:
            async with session.begin():
                await session.merge(
                    AssignmentRow(
                        id=assignment.id,
                        teacher_id=assignment.teacher_id,
                        title=assignment.title,
                        share_token=None if assignment.share is None else assignment.share.token,
                    )
                )
                await session.execute(
                    delete(AssignmentStudentRow).where(AssignmentStudentRow.assignment_id == assignment.id)
                )
                await session.execute(
                    delete(AssignmentCaseRow).where(AssignmentCaseRow.assignment_id == assignment.id)
                )
                session.add_all(
                    AssignmentStudentRow(assignment_id=assignment.id, student_id=student_id, position=index)
                    for index, student_id in enumerate(assignment.student_ids)
                )
                session.add_all(
                    AssignmentCaseRow(assignment_id=assignment.id, case_id=case_id, position=index)
                    for index, case_id in enumerate(assignment.case_ids)
                )

    async def get_assignment(self, assignment_id: str) -> Assignment | None:
        async with self._sessions() as session:
            row = await session.get(AssignmentRow, assignment_id)
            return None if row is None else await self._load(session, row)

    async def find_by_token(self, token: str) -> Assignment | None:
        async with self._sessions() as session:
            row = await session.scalar(select(AssignmentRow).where(AssignmentRow.share_token == token))
            return None if row is None else await self._load(session, row)

    async def list_assignments(self, actor_id: str | None) -> list[Assignment]:
        query = select(AssignmentRow).order_by(AssignmentRow.id)
        if actor_id is not None:
            enrolled = select(AssignmentStudentRow.assignment_id).where(AssignmentStudentRow.student_id == actor_id)
            query = query.where((AssignmentRow.teacher_id == actor_id) | AssignmentRow.id.in_(enrolled))
        async with self._sessions() as session:
            rows = (await session.scalars(query)).all()
            return [await self._load(session, row) for row in rows]

    async def add_submission(self, submission: Submission) -> None:
        async with self._sessions() as session:
            async with session.begin():
                session.add(
                    SubmissionRow(
                        id=submission.id,
                        assignment_id=submission.assignment_id,
                        student_id=submission.student_id,
                        case_id=submission.case_id,
                        text=submission.text,
                        demo_id=submission.demo_id,
                    )
                )

    async def list_submissions(self, assignment_ids: list[str]) -> list[Submission]:
        if not assignment_ids:
            return []
        async with self._sessions() as session:
            rows = await session.scalars(
                select(SubmissionRow).where(SubmissionRow.assignment_id.in_(assignment_ids)).order_by(SubmissionRow.id)
            )
            return [_submission(row) for row in rows]

    async def add_badge(self, badge: Badge) -> bool:
        _, _, unique_reason = badge_key(badge.user_id, badge.code, badge.reason)
        try:
            async with self._sessions() as session:
                async with session.begin():
                    session.add(
                        BadgeRow(
                            id=badge.id,
                            user_id=badge.user_id,
                            code=badge.code,
                            reason=badge.reason,
                            unique_reason=unique_reason,
                        )
                    )
        except IntegrityError:
            return False
        return True

    async def list_badges(self, user_id: str) -> list[Badge]:
        async with self._sessions() as session:
            rows = await session.scalars(select(BadgeRow).where(BadgeRow.user_id == user_id).order_by(BadgeRow.id))
            return [Badge(id=row.id, user_id=row.user_id, code=row.code, reason=row.reason) for row in rows]

    async def get_progress(self, user_id: str, demo_id: str) -> DemoProgress | None:
        async with self._sessions() as session:
            row = await session.get(DemoProgressRow, (user_id, demo_id))
        if row is None:
            return None
        steps = {int(item) for item in row.steps.split(",") if item}
        return DemoProgress(user_id=user_id, demo_id=demo_id, steps_done=steps)

    async def save_progress(self, progress: DemoProgress) -> None:
        steps = ",".join(str(item) for item in sorted(progress.steps_done))
        async with self._sessions() as session:
            async with session.begin():
                await session.merge(DemoProgressRow(user_id=progress.user_id, demo_id=progress.demo_id, steps=steps))

    async def record_quiz(self, *, user_id: str, quiz_id: str, correct: bool) -> None:
        async with self._sessions() as session:
            async with session.begin():
                session.add(QuizAttemptRow(user_id=user_id, quiz_id=quiz_id, correct=correct))

    async def _load(self, session: AsyncSession, row: AssignmentRow) -> Assignment:
        students = await session.scalars(
            select(AssignmentStudentRow.student_id)
            .where(AssignmentStudentRow.assignment_id == row.id)
            .order_by(AssignmentStudentRow.position)
        )
        cases = await session.scalars(
            select(AssignmentCaseRow.case_id)
            .where(AssignmentCaseRow.assignment_id == row.id)
            .order_by(AssignmentCaseRow.position)
        )
        submissions = await session.scalars(
            select(SubmissionRow).where(SubmissionRow.assignment_id == row.id).order_by(SubmissionRow.id)
        )
        return Assignment(
            id=row.id,
            teacher_id=row.teacher_id,
            title=row.title,
            student_ids=tuple(students),
            case_ids=tuple(cases),
            share=None if row.share_token is None else ShareLink(token=row.share_token),
            submissions=[_submission(item) for item in submissions],
        )
