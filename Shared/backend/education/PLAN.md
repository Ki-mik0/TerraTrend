---
domain: education
kind: scope
status: scope
---

# education — що реалізувати

Корінь `Assignment`. Усередині `Submission`. Посилання для класу — значення завдання, не новий корінь.

Окремий корінь `Badge`.

Демо і словник освіта не зберігає. Вона віддає `DemoScenario` і `GlossaryEntry` з каталогу.

## Дії

- Список завдань вчителя або призначених учню.
- Створити завдання. Роль `teacher`.
- Прочитати одне завдання.
- Видати посилання для класу.
- Записати відповідь учня, прив’язану до справи.
- Список відповідей. Роль `teacher`.
- Видати бейдж за пройдене демо або здане завдання і показати бейджі користувача.
- Віддати демо-справи і словник, включно зі сторінкою «Як працює наш ШІ».
- Відкрити завдання за посиланням класу і приєднати до нього учня.
- Вести прогрес кроків демо; останній крок видає бейдж `demo`.
- Віддати вікторини без правильних відповідей і перевірити відповідь.
- Запустити лабораторію статистики через `LabPort`.
- Видати бейджі справи за подією `CaseService`.
- Віддати демо, словник і вікторини українською або англійською (`lang=uk|en`).

## Маршрути

- `GET /api/v1/education/assignments`
- `POST /api/v1/education/assignments`
- `GET /api/v1/education/assignments/{id}`
- `POST /api/v1/education/assignments/{id}/share`
- `GET /api/v1/education/shared/{token}` — що показує посилання класу
- `POST /api/v1/education/shared/{token}/join` — учень приєднується за посиланням
- `POST /api/v1/education/submissions`
- `GET /api/v1/education/submissions?assignment_id=`
- `GET /api/v1/education/badges`
- `GET /api/v1/education/demos?lang=`
- `GET /api/v1/education/demos/{id}?lang=`
- `POST /api/v1/education/demos/{id}/steps/{n}`
- `GET /api/v1/education/glossary?lang=`
- `GET /api/v1/education/quizzes?lang=`
- `POST /api/v1/education/quizzes/{id}`
- `POST /api/v1/education/lab`

## Збереження і кеш

Сховище — `MemoryEducationStore` або `SqlEducationStore` (PostgreSQL за `DB_URL`, міграція `002_education`). Таблиці: `assignments`, `assignment_students`, `assignment_cases`, `submissions`, `badges` (унікальні), `quiz_attempts`, `demo_progress`.

Кеш — `CachePort` (`infrastructure/shared/cache.py`): Redis за `REDIS_URL`, інакше пам’ять. Збій Redis — промах.

| Ключ | Що | TTL |
|---|---|---|
| `edu:demos:{catalog_generation}:{lang}` | демо з кроками | 24 год |
| `edu:glossary:{catalog_generation}:{lang}` | словник | 24 год |
| `edu:quizzes:{bank_version}:{lang}` | питання без відповідей | 24 год |
| `edu:lab:{sha256(params)}` | готовий `LabRun` | 24 год |
| `edu:badges:{user_id}` | бейджі; скидається під час видачі | 10 хв |
| `edu:share:{token}` | token → id завдання; скидається під час перевидачі | 1 год |

Перечитаний каталог змінює `generation`, тож старі демо і словник більше не читаються.

## Бейджі

Усі видачі йдуть через `EducationService.award`, бейдж не дублюється.

- `assignment` — здана відповідь, раз на завдання.
- `demo` — пройдений останній крок демо.
- `quiz` — правильна відповідь вікторини, раз на питання.
- `first_significant_trend` — справа з вироком `proven`, `strong` або `likely`.
- `found_split` — справа з `split_flag`.
- `refuted_false_trend` — вирок `no_evidence` або `suspicious`, і алібі зменшило сирий нахил щонайменше вдвічі або jackknife знайшов `influential_year`.

Три бейджі справи видаються раз на користувача через `AchievementPort` у `CaseService`. Гість і тимчасова справа бейджів не отримують.

## Не входить

Перевірка живності, PNG-тайли, прогрів кешу. Розрахунок лабораторії: `StubLab` відповідає `503 data_not_ready`, доки аналітика не дасть адаптер `LabPort`.

## Готовність — 100

Усе з розділу «Дії» і з «Журнал і освіта» плану бекенду є в коді та покрите тестами. Справжній симулятор лабораторії — робота аналітики за портом `LabPort`.
