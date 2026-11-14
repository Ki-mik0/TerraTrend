"""Quiz bank. Each question exists in Ukrainian and English: `<id>_uk` and `<id>_en`."""

from __future__ import annotations

from earthtrend.api.domain.education.model import Quiz

# id, answer index, {lang: (question, options, explanation)}
_QUIZZES: list[tuple[str, int, dict[str, tuple[str, tuple[str, ...], str]]]] = [
    ("q_p_value", 1, {
        "uk": (
            "p-value = 0.01. Що це означає?",
            ("Тренд точно є", "Такий нахил випадково малоймовірний", "Тренд сильний", "Даних замало"),
            "p-value каже про випадковість, а не про силу чи певність тренду.",
        ),
        "en": (
            "p-value = 0.01. What does it mean?",
            ("The trend is certain", "Such a slope is unlikely by chance", "The trend is strong", "Too little data"),
            "The p-value speaks about chance, not about the strength or certainty of the trend.",
        ),
    }),
    ("q_autocorrelation", 2, {
        "uk": (
            "Чому автокореляція робить тренд менш певним?",
            ("Вона додає шум", "Вона змінює знак", "Незалежних спостережень менше", "Вона прибирає сезонність"),
            "Схожі сусідні роки зменшують ефективну кількість спостережень n_eff.",
        ),
        "en": (
            "Why does autocorrelation make a trend less certain?",
            ("It adds noise", "It flips the sign", "There are fewer independent observations", "It removes seasonality"),
            "Similar neighbouring years reduce the effective number of observations n_eff.",
        ),
    }),
    ("q_witnesses", 0, {
        "uk": (
            "Що доводять «свідки»?",
            ("Тренд видно в незалежних датасетах", "Тренд пояснює Ель-Ніньйо", "Регіон розколотий", "Ряд довгий"),
            "Свідки — інші датасети того самого показника. Їхня згода відкидає артефакт приладу.",
        ),
        "en": (
            "What do the witnesses prove?",
            ("The trend shows in independent datasets", "El Niño explains the trend", "The region is split", "The series is long"),
            "Witnesses are other datasets of the same quantity. Their agreement rules out an instrument artefact.",
        ),
    }),
    ("q_alibi", 3, {
        "uk": (
            "Після алібі нахил упав з −0.04 до −0.01. Що це означає?",
            ("Тренд посилився", "Даних замало", "Регіон розколотий", "Більшу частину зміни пояснюють природні коливання"),
            "Алібі вилучає ENSO, NAO і вулкани. Малий залишок означає, що «тренд» був здебільшого природною мінливістю.",
        ),
        "en": (
            "After the alibi the slope fell from −0.04 to −0.01. What does it mean?",
            ("The trend got stronger", "Too little data", "The region is split", "Natural variability explains most of the change"),
            "The alibi removes ENSO, NAO and volcanoes. A small remainder means the trend was mostly natural variability.",
        ),
    }),
    ("q_fdr", 1, {
        "uk": (
            "Навіщо радару поправка FDR?",
            ("Щоб прискорити розрахунок", "Щоб серед тисяч тестів було мало хибних відкриттів", "Щоб прибрати сезонність", "Щоб згладити карту"),
            "Із тисяч тестів частина буде «значущою» випадково. FDR обмежує їхню частку.",
        ),
        "en": (
            "Why does the radar need the FDR correction?",
            ("To speed up the calculation", "To keep false discoveries rare among thousands of tests", "To remove seasonality", "To smooth the map"),
            "Among thousands of tests some will be significant by luck. FDR limits their share.",
        ),
    }),
    ("q_ai", 2, {
        "uk": (
            "Хто виносить вирок справи?",
            ("Нейромережа M1", "Асистент", "Статистичні правила verdict_rules_v1", "Вчитель"),
            "Думка ШІ дорадча. Вирок рахують прозорі статистичні правила.",
        ),
        "en": (
            "Who decides the case verdict?",
            ("The M1 neural network", "The assistant", "The statistical rules verdict_rules_v1", "The teacher"),
            "The AI opinion is advisory. The verdict comes from transparent statistical rules.",
        ),
    }),
]


def seed_quizzes() -> list[Quiz]:
    return [
        Quiz(
            id=f"{quiz_id}_{language}",
            language=language,
            question=question,
            options=options,
            answer=answer,
            explanation=explanation,
        )
        for quiz_id, answer, texts in _QUIZZES
        for language, (question, options, explanation) in texts.items()
    ]


class MemoryQuizBank:
    version = "quiz-v1"

    def __init__(self, quizzes: list[Quiz] | None = None) -> None:
        self._quizzes = {item.id: item for item in (quizzes if quizzes is not None else seed_quizzes())}

    async def list(self, language: str) -> list[Quiz]:
        return [item for item in self._quizzes.values() if item.language == language]

    async def get(self, quiz_id: str) -> Quiz | None:
        return self._quizzes.get(quiz_id)
