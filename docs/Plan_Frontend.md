# EarthTrend Detective — план фронтенду

Застосунок лежить у `web/`. Стек: Vite, React, TypeScript, Tailwind CSS, HeroUI, MapLibre GL, deck.gl, ECharts, Zustand, TanStack Query, i18next. Малювання полігона — `@maplibre/maplibre-gl-draw`. Залежності вебу ставить npm у `web/node_modules`. Python-оточення `.venv` у корені репозиторію вебу не стосується.

## Контракт із бекендом

Усі виклики йдуть на `/api/v1`. Фронтенд не рахує вирок і не вигадує чисел: малює поля справи і перекладає коди.

| Екран | Звідки дані |
|---|---|
| Вибір змінної | `GET /variables`; поле `q` — пошук M3 або текст каталогу |
| Підказки регіону | `GET /regions/{id}/potential` |
| Полігон | `POST /regions/custom` → `region_id`, далі він у справі |
| Справа | `POST /cases`; тіло `completed` або `202` і `job_id` |
| Прогрес | `EventSource` на `GET /jobs/{id}/events`: `progress`, `stage`, `message`, `completed` |
| Вирок і графіки | `GET /cases/{id}` і `GET /cases/{id}/evidence` |
| Карта | `GET /tiles/{product}/{z}/{x}/{y}.png`, продукт `trend` або `ai_class` |
| Радар | `GET /radar?feed=` |
| Історія | `GET /cases/{id}/story` |
| Чат | `POST /assistant/ask/stream`: `plan`, `tool_start`, `tool_result`, `answer_chunk` |
| Експорт | `POST /cases/{id}/export`, далі `GET /exports/{id}/download` |
| Словник і ШІ | `GET /education/glossary` |

Канонічне посилання готової справи — `/case/:id`. Чернетка в query тримає змінну, період, `region_id`, сезон і режим. Подія `tool_result` оновлює стор (змінна, регіон, справа).

Коди вироку фарбують картку: `proven` і `strong` — за знаком тренду, `likely` — жовтий, `suspicious` — помаранчевий, `no_evidence` і `inadmissible` — сірі. Пункт `ai_expert` колір не змінює. Тексти кодів вироку, `caveats` і патернів історії дає i18n.

## Фаза 1. Каркас

- Застосунок Vite (React + TypeScript), Tailwind і HeroUI, світла і темна тема, палітра для дальтоніків.
- Zustand `useCaseStore`: змінна, період, сезон, `region_id`, режим Просто/Експерт, мова.
- Маршрути: `/` лендінг і радар, `/explore` карта і панелі, `/case/:id` збережена справа, `/learn` словник і «Як працює наш ШІ».
- Layout `/explore`: лівий сайдбар (змінна, дати, сезон), центр під карту, правий сайдбар під вирок і графіки.

## Фаза 2. Карта

- MapLibre і deck.gl, світла і темна підкладка.
- `@maplibre/maplibre-gl-draw` пише GeoJSON у стор і викликає `POST /regions/custom`.
- `TileLayer` на `/api/v1/tiles/trend/{z}/{x}/{y}.png` з query змінної, періоду, сезону і `significant_only`.
- Перемикач шару `ai_class` на той самий шаблон тайлів.
- Штрихування FDR — прапор `significant_only` і контури зон зі зведення справи.

## Фаза 3. Картки

Дані на цій фазі можна підставити фікстурою тієї самої форми, що повертає API.

- Вирок: код, `strength`, напрям, `caveats`. Поруч картка «Думка ШІ» з класом зміни, впевненістю і підписом, що вона не впливає на вирок. Застереження `ai_disagrees` видиме окремо.
- Головний ряд: сирі значення й аномалії, лінія тренду, смуга 95% CI. Кнопка «Прибрати рік» ставить сценарій jackknife і показує `influential_year`.
- Свідки: лінії датасетів одного `concept_id` з `details.witnesses`.
- Трикутник: теплова карта `TriangleResult`, осі — рік початку і рік кінця.
- Алібі: дві лінії, сирий тренд і ряд без алібі (`b_raw`, `b_adjusted`).
- Точки зламу: `markLine` на головному графіку з `changepoints`.
- Якість: пропуски, `n_eff`, `stable_fraction`.

## Фаза 4. Живий API

- TanStack Query.
- Каталог у селект лівої панелі.
- `useAnalyzeCase`: зміна полігона або періоду створює регіон, потім `POST /cases`. Гілка `completed` кладе справу в картки. Гілка `202` відкриває `EventSource` і HeroUI `Progress` з `stage` і `message`.
- Після справи блок підказок M2 показує «підтвердилось / ні» проти `GET /regions/{id}/potential`.
- Чернетка синхронізується з query. Після `completed` адреса стає `/case/:id`.

## Фаза 5. Радар, історія, асистент, експорт

- Стрічки радару: `strongest`, `opposite`, `accelerating`, `breakpoints`, `almost`, `stable`, `ai_flagged`. Картка відкриває `/case/:id`.
- Story Lens: текст відповіді, міні-графіки співучасників, коди патернів через i18n.
- Чат: плаваюча кнопка або сайдбар, стрім `/assistant/ask/stream`, друк шматками, `tool_result` міняє змінну і регіон у сторі.
- Експорт: кнопки PDF і CSV викликають `POST /cases/{id}/export` і завантажують файл. Той самий шлях для ipynb, html, png, geojson і zip.
- Майстер на головній: «ШІ радить перевірити» з імовірностями і кодами причин M2.

## Фаза 6. Полірування

- На вузькому екрані панелі ховаються в HeroUI `Drawer`.
- Помилки API (`code`, `message`) — Toast або запасний блок.
- i18n UA/EN для кодів. Мова запиту справи і історії збігається з мовою інтерфейсу.
- `/learn`: словник і сторінка «Як працює наш ШІ» з `GET /education/glossary`, плюс лабораторія шуму на фіксованих тестових рядах, звірених з аналітикою.
