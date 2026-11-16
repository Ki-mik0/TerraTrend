# TerraTrend

EarthTrend Detective для теми Earth System Trend Detective на NASA Space Apps Challenge Dnipro 2026. Бекенд — один пакет `earthtrend`: API на Litestar і аналітика поруч. Зараз зібраний API каталогу, справ, радару, історії, асистента, задач, експорту, журналу, освіти й сесії.

## Локально

Потрібен Python 3.12 або новіший.

```powershell
py -3 -m pip install -e ".[dev]"
Copy-Item .env.example .env
py -3 -m uvicorn earthtrend.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

Якщо встановлений `uv`, той самий крок встановлення — `uv sync --extra dev`. Сервер слухає [http://127.0.0.1:8000](http://127.0.0.1:8000). Документація Scalar — [http://127.0.0.1:8000/schema](http://127.0.0.1:8000/schema), той самий екран також на `/schema/scalar`. JSON-схема — [http://127.0.0.1:8000/schema/openapi.json](http://127.0.0.1:8000/schema/openapi.json).

Каталог і радар читаються без токена. Решта маршрутів чекає `Authorization: Bearer`. Гостьовий токен:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/session/guest
```

## Docker

Docker Compose піднімає API, PostgreSQL і Redis. Том `./data` лишається для файлів експорту.

```powershell
docker compose up --build api
docker compose --profile test run --rm tests
```

API на хості: [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Контракт API для фронтенду

Джерело правди — код Litestar. З нього генерується `contract/openapi.json`, а з нього — типи фронтенду `web/src/api/schema.d.ts`. Руками ці файли не редагують.

```
src/earthtrend/api  →  contract/openapi.json  →  web/src/api/schema.d.ts  →  api (openapi-fetch)
```

- `python scripts/contract.py --web` (`make contract`) — оновити контракт і TS-типи.
- `python scripts/contract.py --watch` (`make contract-watch`) — оновлювати на кожне збереження в `src/earthtrend/api` під час розробки.
- `git config core.hooksPath .githooks` (`make hooks`, раз на клон) — pre-commit сам оновлює і додає обидва файли в коміт, якщо змінено бекенд.
- `tests/api/test_contract.py` і CI (`.github/workflows/contract.yml`) падають, якщо контракт застарів, типи не відповідають контракту або фронт не компілюється з новими типами.

На фронті запити йдуть через типізований клієнт:

```ts
import { api, type Schema } from "./api/client"; // з web/src
const { data, error } = await api.POST("/api/v1/cases", { body: { variable_id, region_id, period_start, period_end } });
```

Якщо бекенд перейменує поле чи шлях, `npm --prefix web run typecheck` покаже кожне місце у фронті, яке треба виправити.

## Дані NASA

Карта трендів, радар і справи читають реальні дані з `STORAGE_ROOT` (`data/storage`, у git не потрапляє). Скрипти можна переривати: повторний запуск докачує лише те, чого бракує. Запущений API підхоплює нові файли без перезапуску.

| Скрипт | Звідки | Що будує |
|---|---|---|
| `scripts/radar_scan.py` | NASA POWER, без акаунта | радар: 16 регіонів × 5 змінних |
| `scripts/grid_scan.py` | NASA POWER, без акаунта | сітки 1° для 7 змінних (MERRA-2 через POWER) |
| `scripts/earthdata_grids.py` | NASA Earthdata, потрібен акаунт | сітки 1° і місячні ряди для 30 змінних каталогу |

```powershell
.venv/Scripts/python scripts/radar_scan.py
.venv/Scripts/python scripts/grid_scan.py --workers 3
.venv/Scripts/python scripts/earthdata_grids.py --list    # джерела і змінні
.venv/Scripts/python scripts/earthdata_grids.py           # усе, кілька годин; --only gldas airs — частина
```

Для Earthdata:

1. Зареєструйся на [urs.earthdata.nasa.gov](https://urs.earthdata.nasa.gov).
2. У розділі Applications → Authorized Apps схвали «NASA GESDISC DATA ARCHIVE».
3. Один раз увійди: `python -c "import earthaccess; earthaccess.login(persist=True)"`. Логін збережеться в `~/_netrc`.
4. Встанови залежності: `pip install -e ".[data]"`.

Як скрипт бере дані:

- з колекцій GES DISC (MERRA-2, AIRS, денний IMERG) — лише потрібну змінну, вирізану на сервері через Cloud OPeNDAP;
- HDF5 (GLDAS, IMERG, OMI, NSIDC, колір океану) — цілим файлом у пам'ять;
- HDF4 MODIS — на диск, після читання файл одразу видаляється.

Кожна гранула одразу зводиться до сітки 1° і кешується в `grids/earthdata-raw/`. Місячні куби лягають у `grids/series/`. З них справа рахує ряд для регіону: середнє клітинок усередині рамки, зважене за площею. Такі справи мають позначку «NASA Earthdata».

`--heavy` додає `modis_aod` (MYD08_M3, близько 100 ГБ). Без реальних даних лишаються дві змінні: `modis_phenology` і `season_bounds`.

## Тести

```powershell
py -3 -m pytest
```

Поріг покриття `earthtrend.api` — 85%. Три інтеграційні тести в `tests/integration` самі пропускаються, доки не задано `API_URL`. У Compose їх запускає профіль `test`.

## Змінні

`.env.example` задає `ENV`, `DB_URL`, `REDIS_URL`, `STORAGE_ROOT`, `CATALOG_DIR`, `MODELS_DIR`. Якщо `DB_URL` починається з `postgresql`, користувачі, ключі, аудит і рев’ю пишуться в PostgreSQL. Без цієї змінної процес тримає їх у пам’яті, тож тести інших доменів не вимагають бази. `REDIS_URL` кешує перевірку сесії на 60 секунд. Якщо Redis недоступний, читання сесії йде в базу. Якщо в оточенні є `OPENROUTER_API_KEY`, історія і асистент звертаються до моделі через OpenRouter. Без ключа лишається локальний шаблон. Секрет JWT для локальної розробки зашитий у коді токенів і не читається з `.env`.

## Чому PostgreSQL і Redis

Стан застосунку живе в PostgreSQL. Identity вже пише туди користувачів, ключі, журнал аудиту і рев’ю розбіжностей ШІ. Ключ API у базі зберігається лише як хеш. Випуск ключа і рядок аудиту йдуть однією транзакцією: зірваний аудит не лишає ключа.

Redis тримає короткий кеш «цей користувач ще існує і має цю роль», щоб кожен запит із токеном не читав базу. У кеш не потрапляють пароль і хеш. Відмова Redis не зупиняє вхід: сервіс читає PostgreSQL.

Справи, журнал, освіта, задачі й експорт у базі ще не лежать. Їхні наступні репозиторії підключаються до того самого `DB_URL`.
