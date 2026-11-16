/**
 * Plain-language explanations of every technical word the interface shows.
 * Each entry: [title uk, text uk, title en, text en].
 */
export const TERMS = {
  trend: [
    "Тренд",
    "Напрям, у якому величина змінюється за багато років: зростає, спадає чи лишається сталою. Окремі теплі чи холодні роки не рахуються — важить довга лінія.",
    "Trend",
    "The direction a quantity moves over many years: up, down or flat. Single warm or cold years do not count — the long line does.",
  ],
  slope: [
    "Зміна за 10 років",
    "На скільки в середньому змінюється величина кожні 10 років. +0.5 °C означає: що десятиліття стає на пів градуса тепліше.",
    "Change per decade",
    "How much the quantity changes on average every 10 years. +0.5 °C means half a degree warmer each decade.",
  ],
  verdict: [
    "Вирок",
    "Підсумок перевірки. Система не довіряє одному тесту: вона збирає шість доказів і за правилами вирішує, наскільки тренд переконливий.",
    "Verdict",
    "The bottom line. The system does not trust a single test: it gathers six pieces of evidence and rules how convincing the trend is.",
  ],
  p_value: [
    "p-value",
    "Ймовірність побачити такий тренд випадково, якби насправді нічого не змінювалось. Чим менше — тим менш імовірна випадковість. Менше 0.05 вважають значущим.",
    "p-value",
    "The chance of seeing such a trend by luck if nothing really changed. Smaller means luck is less likely. Below 0.05 counts as significant.",
  ],
  q_fdr: [
    "q (поправка FDR)",
    "Радар перевіряє тисячі пар змінна × регіон, і частина «знахідок» неминуче буде випадковою. q — це p-value з поправкою на кількість перевірок; чим менше, тим надійніше.",
    "q (FDR correction)",
    "The radar checks thousands of variable × region pairs, so some “findings” are bound to be luck. q is the p-value corrected for the number of checks; smaller is more reliable.",
  ],
  snr: [
    "Сигнал / шум",
    "Наскільки тренд помітний на тлі звичайних коливань. Менше 0.2 — слабкий, 0.2–0.5 — помірний, понад 0.5 — сильний.",
    "Signal / noise",
    "How visible the trend is against normal ups and downs. Below 0.2 is weak, 0.2–0.5 moderate, above 0.5 strong.",
  ],
  n_eff: [
    "Ефективна кількість точок",
    "Сусідні роки схожі між собою, тому незалежних спостережень менше, ніж місяців у ряді. Що менше n_eff, то обережніше треба ставитися до тренду.",
    "Effective sample size",
    "Neighbouring years resemble each other, so there are fewer independent observations than months. The smaller n_eff, the more careful one must be.",
  ],
  witnesses: [
    "Свідки",
    "Інші незалежні набори даних про ту саму величину (інший супутник чи модель). Якщо вони бачать той самий тренд, це не помилка одного приладу.",
    "Witnesses",
    "Other independent datasets of the same quantity (another satellite or model). If they see the same trend, it is not one instrument’s error.",
  ],
  robustness: [
    "Стійкість",
    "Ми перераховуємо тренд для всіх можливих періодів (з різних років до різних років). Якщо знак здебільшого той самий, висновок не залежить від вдало вибраних дат.",
    "Robustness",
    "The trend is recomputed for every possible start and end year. If the sign mostly holds, the result does not hinge on cherry-picked dates.",
  ],
  alibi: [
    "Алібі",
    "Природні причини, які теж змінюють клімат: Ель-Ніньйо, коливання над Атлантикою, вулканічний пил. Ми їх вилучаємо і дивимось, чи лишається тренд.",
    "Alibi",
    "Natural causes that also move the climate: El Niño, Atlantic oscillations, volcanic dust. We remove them and check whether the trend survives.",
  ],
  quality: [
    "Якість даних",
    "Скільки місяців бракує в ряді і чи стабільно прилад спостерігав регіон. Багато пропусків — менше довіри.",
    "Data quality",
    "How many months are missing and whether the region was observed steadily. Many gaps mean less trust.",
  ],
  significant: [
    "Значущий",
    "Тренд настільки виразний, що випадково таке було б дуже малоймовірно.",
    "Significant",
    "The trend is so clear that it would be very unlikely to happen by chance.",
  ],
  ai_class: [
    "Клас ШІ",
    "Нейромережа дивиться на форму ряду: рівна лінія, стрибок, прискорення чи зсув сезонів. Це дорадча думка — на вирок вона не впливає.",
    "AI class",
    "A neural network looks at the shape of the series: a straight line, a jump, acceleration or a seasonal shift. Advisory only — it never changes the verdict.",
  ],
  years_to_proof: [
    "Років до доказу",
    "Скільки ще років спостережень потрібно, щоб тренд такої сили став статистично доведеним.",
    "Years to proof",
    "How many more years of data a trend this strong needs before it can be proven.",
  ],
  fdr_only: [
    "Лише значущі після FDR",
    "Показати тільки ті місця, де тренд проходить сувору перевірку з поправкою на тисячі одночасних тестів.",
    "Significant after FDR only",
    "Show only places where the trend passes a strict check corrected for thousands of simultaneous tests.",
  ],
  demo_data: [
    "Демо-дані",
    "Для цієї пари ще немає реальних даних, тому система показує навчальний синтетичний ряд. Він підходить, щоб зрозуміти інструменти, але не для висновків про реальний світ.",
    "Demo data",
    "There is no real data for this pair yet, so the system uses a synthetic teaching series. Good for learning the tools, not for real-world conclusions.",
  ],
  nasa_power: [
    "NASA POWER",
    "Реальні щомісячні дані NASA, зібрані з супутників і кліматичних моделей. Для регіону беремо середнє з кількох точок.",
    "NASA POWER",
    "Real monthly NASA data combining satellites and climate models. For a region we average several points.",
  ],
  nasa_earthdata: [
    "NASA Earthdata",
    "Реальні щомісячні дані саме тієї місії NASA, що названа у змінній (MERRA-2, GLDAS, IMERG, MODIS, OMI, GRACE, AIRS, NSIDC). Для регіону беремо середнє з клітинок сітки 1° усередині нього, зважене за площею.",
    "NASA Earthdata",
    "Real monthly data from the very NASA mission named in the variable (MERRA-2, GLDAS, IMERG, MODIS, OMI, GRACE, AIRS, NSIDC). For a region we take the area-weighted mean of the 1° grid cells inside it.",
  ],
} as const;

export type TermId = keyof typeof TERMS;

/** What each verdict level means, in reader terms. Order: strongest first. */
export const VERDICT_MEANING: Array<[code: string, uk: string, en: string]> = [
  ["proven", "Тренд підтверджують усі перевірки: статистика, свідки, стійкість і алібі.", "Every check agrees: statistics, witnesses, robustness and the alibi."],
  ["strong", "Статистика однозначна, і щонайменше дві інші перевірки її підтримують.", "The statistics are clear and at least two other checks back them."],
  ["likely", "Статистика за тренд, але свідки чи стійкість ще сумніваються.", "The statistics point to a trend, but witnesses or robustness still doubt it."],
  ["suspicious", "Схоже на тренд, але доказів поки замало — потрібно більше років даних.", "It looks like a trend, but there is not enough evidence yet — more years are needed."],
  ["no_evidence", "Помітного тренду немає: зміни не виходять за межі звичайних коливань.", "No noticeable trend: changes stay within normal ups and downs."],
  ["inadmissible", "Справу не можна розглянути: замало даних або вони погані.", "The case cannot be judged: too little or poor data."],
];
