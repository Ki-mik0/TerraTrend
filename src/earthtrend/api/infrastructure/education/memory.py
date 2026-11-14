"""In-memory education store for tests and local runs."""

from __future__ import annotations

from dataclasses import replace

from earthtrend.api.domain.education.model import Assignment, Badge, DemoProgress, Submission, badge_key


class MemoryEducationStore:
    def __init__(self) -> None:
        self.assignments: dict[str, Assignment] = {}
        self.submissions: list[Submission] = []
        self.badges: dict[tuple[str, str, str], Badge] = {}
        self.progress: dict[tuple[str, str], DemoProgress] = {}
        self.quiz_attempts: list[tuple[str, str, bool]] = []

    async def save_assignment(self, assignment: Assignment) -> None:
        self.assignments[assignment.id] = assignment

    async def get_assignment(self, assignment_id: str) -> Assignment | None:
        return self.assignments.get(assignment_id)

    async def find_by_token(self, token: str) -> Assignment | None:
        for item in self.assignments.values():
            if item.share is not None and item.share.token == token:
                return item
        return None

    async def list_assignments(self, actor_id: str | None) -> list[Assignment]:
        return [
            item
            for item in self.assignments.values()
            if actor_id is None or item.teacher_id == actor_id or actor_id in item.student_ids
        ]

    async def add_submission(self, submission: Submission) -> None:
        self.submissions.append(submission)
        assignment = self.assignments.get(submission.assignment_id)
        if assignment is not None:
            assignment.submissions.append(submission)

    async def list_submissions(self, assignment_ids: list[str]) -> list[Submission]:
        wanted = set(assignment_ids)
        return [item for item in self.submissions if item.assignment_id in wanted]

    async def add_badge(self, badge: Badge) -> bool:
        key = badge_key(badge.user_id, badge.code, badge.reason)
        if key in self.badges:
            return False
        self.badges[key] = badge
        return True

    async def list_badges(self, user_id: str) -> list[Badge]:
        return [item for item in self.badges.values() if item.user_id == user_id]

    async def get_progress(self, user_id: str, demo_id: str) -> DemoProgress | None:
        found = self.progress.get((user_id, demo_id))
        return None if found is None else replace(found, steps_done=set(found.steps_done))

    async def save_progress(self, progress: DemoProgress) -> None:
        self.progress[(progress.user_id, progress.demo_id)] = replace(progress, steps_done=set(progress.steps_done))

    async def record_quiz(self, *, user_id: str, quiz_id: str, correct: bool) -> None:
        self.quiz_attempts.append((user_id, quiz_id, correct))
