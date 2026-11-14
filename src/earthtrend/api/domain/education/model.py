"""Education aggregates. Demos and the glossary stay in the catalog."""

from __future__ import annotations

from dataclasses import dataclass, field

LANGUAGES = ("uk", "en")
SIGNIFICANT_VERDICTS = frozenset({"proven", "strong", "likely"})
WEAK_VERDICTS = frozenset({"no_evidence", "suspicious"})
ONCE_PER_USER = frozenset({"first_significant_trend", "found_split", "refuted_false_trend"})
BADGE_CODES = frozenset({"assignment", "demo", "quiz", *ONCE_PER_USER})


class EducationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def require_language(language: str) -> str:
    if language not in LANGUAGES:
        raise EducationError("invalid_language", "Мова має бути uk або en")
    return language


@dataclass(frozen=True)
class ShareLink:
    token: str


@dataclass
class Submission:
    id: str
    assignment_id: str
    student_id: str
    case_id: str
    text: str
    demo_id: str | None = None


@dataclass
class Assignment:
    id: str
    teacher_id: str
    title: str
    student_ids: tuple[str, ...]
    case_ids: tuple[str, ...]
    share: ShareLink | None = None
    submissions: list[Submission] = field(default_factory=list)

    def visible_to(self, actor_id: str, role: str) -> bool:
        if role == "admin" or (role == "teacher" and actor_id == self.teacher_id):
            return True
        return actor_id in self.student_ids

    def owned_by(self, actor_id: str, role: str) -> bool:
        return role == "admin" or self.teacher_id == actor_id

    def join(self, student_id: str, role: str) -> bool:
        """Add a student who opened the class link. Return True when the roster changed."""
        if role == "guest":
            raise EducationError("forbidden", "Гість не може приєднатися до завдання")
        if student_id == self.teacher_id or student_id in self.student_ids:
            return False
        self.student_ids = (*self.student_ids, student_id)
        return True

    def accepts_case(self, case_id: str, case_owner_id: str, student_id: str) -> bool:
        """A submission cites a case of the assignment or the student's own investigation."""
        return case_id in self.case_ids or case_owner_id == student_id


@dataclass
class Badge:
    id: str
    user_id: str
    code: str
    reason: str


def badge_key(user_id: str, code: str, reason: str) -> tuple[str, str, str]:
    """Uniqueness key: case badges are earned once per user, the rest once per reason."""
    if code not in BADGE_CODES:
        raise EducationError("invalid_badge", "Невідомий код бейджа")
    return (user_id, code, "" if code in ONCE_PER_USER else reason)


def badges_for_case(
    *,
    verdict_code: str,
    split_flag: bool,
    b_raw: float,
    b_adjusted: float,
    influential_year: int | None,
) -> list[str]:
    """Badges a completed case earns. The verdict is computed by analytics, not here."""
    codes: list[str] = []
    if verdict_code in SIGNIFICANT_VERDICTS:
        codes.append("first_significant_trend")
    if split_flag:
        codes.append("found_split")
    if verdict_code in WEAK_VERDICTS:
        alibi_explains = b_raw != 0 and abs(b_adjusted) <= 0.5 * abs(b_raw)
        if alibi_explains or influential_year is not None:
            codes.append("refuted_false_trend")
    return codes


@dataclass(frozen=True)
class Quiz:
    id: str
    language: str
    question: str
    options: tuple[str, ...]
    answer: int
    explanation: str
    badge_code: str = "quiz"

    def check(self, choice: int) -> bool:
        if choice < 0 or choice >= len(self.options):
            raise EducationError("invalid_answer", "Такого варіанта немає")
        return choice == self.answer


@dataclass(frozen=True)
class QuizResult:
    quiz_id: str
    correct: bool
    explanation: str
    badge: str | None


@dataclass
class DemoProgress:
    user_id: str
    demo_id: str
    steps_done: set[int] = field(default_factory=set)

    def complete_step(self, step: int, total: int) -> bool:
        """Mark a step done. Return True when this call finished the whole demo."""
        if step < 1 or step > total:
            raise EducationError("invalid_step", "Такого кроку в демо немає")
        was_done = self.finished(total)
        self.steps_done.add(step)
        return not was_done and self.finished(total)

    def finished(self, total: int) -> bool:
        return total > 0 and len(self.steps_done) >= total


@dataclass(frozen=True)
class LabParams:
    noise: float
    years: int
    autocorrelation: float
    trend_per_decade: float = 0.2
    seed: int = 0

    def __post_init__(self) -> None:
        if self.noise < 0 or self.noise > 10:
            raise EducationError("invalid_lab", "Шум має бути від 0 до 10")
        if self.years < 5 or self.years > 100:
            raise EducationError("invalid_lab", "Довжина ряду — від 5 до 100 років")
        if self.autocorrelation < 0 or self.autocorrelation >= 0.95:
            raise EducationError("invalid_lab", "Автокореляція — від 0 до 0.95")


@dataclass(frozen=True)
class LabRun:
    """A temporary reading for the statistics lab. It never becomes a case."""

    params: LabParams
    status: str
    slope_decade: float | None = None
    p_value: float | None = None
    n_eff: float | None = None
    significant: bool | None = None
    series: tuple[float, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == "ready"


def require_teacher(role: str) -> None:
    if role != "teacher" and role != "admin":
        raise EducationError("forbidden", "Це може зробити лише вчитель")
