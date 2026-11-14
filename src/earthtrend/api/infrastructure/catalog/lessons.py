"""Seed lessons: the seven demo cases of BEST §9 and the glossary, in Ukrainian and English."""

from __future__ import annotations

from earthtrend.api.domain.catalog.model import DemoScenario, DemoStep, GlossaryEntry

# id, tool, variable, region, period, {lang: (title, summary, [(step title, step text, ui target)])}
_DEMOS: list[tuple[str, str, str, str, tuple[str, str], dict[str, tuple[str, str, list[tuple[str, str, str]]]]]] = [
    (
        "demo_one_process",
        "vertical_profile",
        "merra2_t_profile",
        "global",
        ("1980-01", "2024-12"),
        {
            "uk": (
                "Один процес — два напрямки",
                "Тропосфера гріється, стратосфера холоне: та сама причина дає протилежні тренди.",
                [
                    ("Відкрий справу", "Обери температуру на рівнях тиску для всієї планети.", "variable"),
                    ("Поверхи будинку", "Подивись на тренд від поверхні до стратосфери.", "profile"),
                    ("Знайди зміну знаку", "Знайди рівень, де потепління змінюється охолодженням.", "profile"),
                    ("Висновок", "Поясни, чому парникові гази дають обидва тренди.", "verdict"),
                ],
            ),
            "en": (
                "One process, two directions",
                "The troposphere warms while the stratosphere cools: one cause, opposite trends.",
                [
                    ("Open the case", "Pick temperature on pressure levels for the whole planet.", "variable"),
                    ("Floors of the house", "Look at the trend from the surface to the stratosphere.", "profile"),
                    ("Find the sign change", "Find the level where warming turns into cooling.", "profile"),
                    ("Conclusion", "Explain why greenhouse gases produce both trends.", "verdict"),
                ],
            ),
        },
    ),
    (
        "demo_clean_air",
        "split",
        "omi_no2",
        "usa_europe_south_asia",
        ("2005-01", "2024-12"),
        {
            "uk": (
                "Справа про чисте повітря",
                "NO₂ над містами США і Європи падає, а над Південною Азією росте.",
                [
                    ("Обери забруднення", "Відкрий NO₂ і великий регіон з кількох континентів.", "variable"),
                    ("Дві версії подій", "Подивись на зони зростання і спадання.", "zones"),
                    ("Людський чинник", "Порівняй тренд із правилами про викиди.", "story"),
                ],
            ),
            "en": (
                "The clean air case",
                "NO₂ falls over US and European cities and rises over South Asia.",
                [
                    ("Pick the pollutant", "Open NO₂ over a region spanning several continents.", "variable"),
                    ("Two versions of events", "Look at the zones of increase and decrease.", "zones"),
                    ("The human factor", "Compare the trend with emission rules.", "story"),
                ],
            ),
        },
    ),
    (
        "demo_arctic",
        "witnesses",
        "merra2_t2m",
        "arctic",
        ("1980-01", "2024-12"),
        {
            "uk": (
                "Арктика гріється найшвидше",
                "Найсильніші докази: усі свідки погоджуються, висновок стійкий до періоду.",
                [
                    ("Відкрий Арктику", "Обери температуру повітря і регіон Арктики.", "region"),
                    ("Свідки", "Перевір, скільки незалежних датасетів підтверджують тренд.", "witnesses"),
                    ("Трикутник", "Подивись, чи тримається знак для різних періодів.", "triangle"),
                    ("Вирок", "Прочитай, чому вирок «доведено».", "verdict"),
                ],
            ),
            "en": (
                "The Arctic warms fastest",
                "The strongest evidence: every witness agrees and the result holds for any period.",
                [
                    ("Open the Arctic", "Pick air temperature and the Arctic region.", "region"),
                    ("Witnesses", "Check how many independent datasets confirm the trend.", "witnesses"),
                    ("Triangle", "See whether the sign holds for different periods.", "triangle"),
                    ("Verdict", "Read why the verdict is 'proven'.", "verdict"),
                ],
            ),
        },
    ),
    (
        "demo_el_nino",
        "alibi",
        "gpm_precip",
        "tropical_pacific",
        ("1998-01", "2024-12"),
        {
            "uk": (
                "Чи це просто Ель-Ніньйо?",
                "Тропічні опади: як алібі змінює висновок.",
                [
                    ("Сирий тренд", "Подивись на тренд опадів без поправок.", "series"),
                    ("Алібі", "Вилучи вплив Niño 3.4 і подивись на залишок.", "alibi"),
                    ("Порівняй", "Порівняй нахил до і після алібі.", "alibi"),
                ],
            ),
            "en": (
                "Is it just El Niño?",
                "Tropical rainfall: how an alibi changes the conclusion.",
                [
                    ("Raw trend", "Look at the rainfall trend without adjustments.", "series"),
                    ("Alibi", "Remove the Niño 3.4 influence and look at the remainder.", "alibi"),
                    ("Compare", "Compare the slope before and after the alibi.", "alibi"),
                ],
            ),
        },
    ),
    (
        "demo_urban_heat",
        "urban_contrast",
        "modis_lst_night",
        "kyiv",
        ("2003-01", "2024-12"),
        {
            "uk": (
                "Місто гріється швидше за околиці?",
                "Міський острів тепла вночі за MODIS LST.",
                [
                    ("Обери місто", "Відкрий нічну температуру поверхні над містом.", "region"),
                    ("Сусіди", "Порівняй тренд міста з кільцем навколо.", "urban"),
                    ("Різниця", "Прочитай, наскільки місто гріється швидше.", "verdict"),
                ],
            ),
            "en": (
                "Does the city warm faster than its suburbs?",
                "The night-time urban heat island from MODIS LST.",
                [
                    ("Pick a city", "Open night land surface temperature over a city.", "region"),
                    ("Neighbours", "Compare the city trend with the ring around it.", "urban"),
                    ("The difference", "Read how much faster the city warms.", "verdict"),
                ],
            ),
        },
    ),
    (
        "demo_groundwater",
        "years_to_proof",
        "grace_tws",
        "north_india",
        ("2002-04", "2024-12"),
        {
            "uk": (
                "Зникаючі підземні води",
                "GRACE над Північною Індією: тренд, невидимий оком.",
                [
                    ("Відкрий GRACE", "Обери запас води на суходолі над Північною Індією.", "variable"),
                    ("Роки до доказу", "Подивись, скільки років знадобилось, щоб тренд став значущим.", "power"),
                    ("Момент злочину", "Знайди точку зламу і звір її з подіями сенсора.", "changepoints"),
                ],
            ),
            "en": (
                "Vanishing groundwater",
                "GRACE over North India: a trend you cannot see by eye.",
                [
                    ("Open GRACE", "Pick terrestrial water storage over North India.", "variable"),
                    ("Years to proof", "See how many years it took for the trend to become significant.", "power"),
                    ("Moment of the crime", "Find the change point and check it against sensor events.", "changepoints"),
                ],
            ),
        },
    ),
    (
        "demo_ukraine_soil",
        "story",
        "gldas_sm",
        "ukraine_south",
        ("2000-01", "2024-12"),
        {
            "uk": (
                "Ґрунти України влітку",
                "Локальна справа: результат перевіряємо на даних, а не стверджуємо заздалегідь.",
                [
                    ("Гіпотеза", "Запиши, що, на твою думку, стається з вологою ґрунту влітку.", "journal"),
                    ("Справа", "Відкрий вологу ґрунту для півдня України, сезон JJA.", "variable"),
                    ("Story Lens", "Прочитай історію, зібрану з фактів справи.", "story"),
                    ("Перевір гіпотезу", "Порівняй вирок зі своєю гіпотезою.", "verdict"),
                ],
            ),
            "en": (
                "Ukraine's soils in summer",
                "A local case: we test the result on data instead of asserting it in advance.",
                [
                    ("Hypothesis", "Write down what you think happens to summer soil moisture.", "journal"),
                    ("Case", "Open soil moisture for southern Ukraine, season JJA.", "variable"),
                    ("Story Lens", "Read the story built from the case facts.", "story"),
                    ("Check the hypothesis", "Compare the verdict with your hypothesis.", "verdict"),
                ],
            ),
        },
    ),
]

# id, kind, {lang: (term, text, example)}
_GLOSSARY: list[tuple[str, str, dict[str, tuple[str, str, str]]]] = [
    ("trend", "term", {
        "uk": ("Тренд", "Напрям зміни за довгий час.", "Волога ґрунту на півдні України влітку спадає."),
        "en": ("Trend", "The direction of change over a long time.", "Summer soil moisture in southern Ukraine declines."),
    }),
    ("anomaly", "term", {
        "uk": ("Аномалія", "Відхилення від звичного для цього місяця значення.", "Липень 2010 був на 4 °C тепліший за норму."),
        "en": ("Anomaly", "A departure from the usual value for that month.", "July 2010 was 4 °C warmer than normal."),
    }),
    ("seasonality", "term", {
        "uk": ("Сезонність", "Повторюваний річний цикл, який прибирають перед пошуком тренду.", "Літо щороку тепліше за зиму."),
        "en": ("Seasonality", "The repeating yearly cycle removed before looking for a trend.", "Summer is warmer than winter every year."),
    }),
    ("p_value", "term", {
        "uk": ("p-value", "Ймовірність побачити такий нахил випадково, якщо тренду немає.", "p = 0.01: випадковість малоймовірна."),
        "en": ("p-value", "The chance of seeing such a slope by luck if there is no trend.", "p = 0.01: luck is unlikely."),
    }),
    ("confidence_interval", "term", {
        "uk": ("Довірчий інтервал", "Діапазон, у якому з імовірністю 95% лежить справжній нахил.", "−0.05…−0.01 за десятиліття."),
        "en": ("Confidence interval", "The range that holds the true slope with 95% probability.", "−0.05…−0.01 per decade."),
    }),
    ("autocorrelation", "term", {
        "uk": ("Автокореляція", "Сусідні роки схожі, тож незалежних спостережень менше (n_eff).", "Посушливий рік часто йде за посушливим."),
        "en": ("Autocorrelation", "Neighbouring years are alike, so there are fewer independent observations (n_eff).", "A dry year often follows a dry year."),
    }),
    ("fdr", "term", {
        "uk": ("FDR", "Поправка на тисячі тестів: обмежує частку хибних відкриттів.", "Радар показує лише тренди після FDR."),
        "en": ("FDR", "A correction for thousands of tests that limits the share of false discoveries.", "The radar shows only trends that pass FDR."),
    }),
    ("how_our_ai_works", "page", {
        "uk": (
            "Як працює наш ШІ",
            "Вирок рахують статистичні правила verdict_rules_v1, а не нейромережа. "
            "Модель M1 дає дорадчу думку про клас зміни і не змінює вирок. "
            "M2 підказує, де тренд імовірний, M3 шукає змінні за змістом, M4 пише текст лише з чисел справи. "
            "Якщо ШІ не згоден зі статистикою, ми показуємо застереження ai_disagrees.",
            "",
        ),
        "en": (
            "How our AI works",
            "The verdict comes from the statistical rules verdict_rules_v1, not from a neural network. "
            "Model M1 gives an advisory opinion on the type of change and never alters the verdict. "
            "M2 suggests where a trend is likely, M3 searches variables by meaning, M4 writes text only from the case numbers. "
            "When the AI disagrees with the statistics we show the ai_disagrees caveat.",
            "",
        ),
    }),
]


def seed_demos() -> list[DemoScenario]:
    demos: list[DemoScenario] = []
    for demo_id, tool, variable_id, region_id, (start, end), texts in _DEMOS:
        for language, (title, summary, steps) in texts.items():
            demos.append(
                DemoScenario(
                    id=demo_id,
                    title=title,
                    language=language,
                    summary=summary,
                    tool=tool,
                    variable_id=variable_id,
                    region_id=region_id,
                    period_start=start,
                    period_end=end,
                    steps=tuple(DemoStep(title=s_title, text=s_text, target=target) for s_title, s_text, target in steps),
                )
            )
    return demos


def seed_glossary() -> list[GlossaryEntry]:
    return [
        GlossaryEntry(id=entry_id, term=term, text=text, language=language, example=example, kind=kind)
        for entry_id, kind, texts in _GLOSSARY
        for language, (term, text, example) in texts.items()
    ]
