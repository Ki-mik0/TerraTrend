---
domain: health
kind: scope
status: done
---

# health — що реалізувати

`HealthCheck` із трьома видами. Проба (`Probe`) ніколи не кидає виняток: вона повертає `ok`, `degraded`, `down` або `skipped`.

## Дії

- **live** — процес відповідає. Залежності не чіпає.
- **ready** — критичні проби (`database`, `storage`) мають бути `ok` або `skipped`. Інакше `503`.
- **full** — усі проби, версія застосунку, uptime. Збій некритичної проби дає `degraded` і `200`; збій критичної — `down` і `503`.
- Кожна проба має тайм-аут 2 с. Тайм-аут або виняток — `down`, у `detail` лише тип помилки, без URL і паролів.

| Проба | Критична | Що перевіряє |
|---|---|---|
| `database` | так | `SELECT 1` у PostgreSQL з `DB_URL`; без нього `skipped` |
| `storage` | так | запис і читання файлу в `STORAGE_ROOT` |
| `cache` | ні | `PING` спільного Redis; без `REDIS_URL` `skipped` |
| `analytics` | ні | версії продуктів радару й сіток; вбудований seed — `degraded` |
| `models` | ні | каталог `MODELS_DIR` і знайдені M1–M4 |

## Маршрути

- `GET /health/live`
- `GET /health/ready`
- `GET /health`

Поза `/api/v1`, публічні, `Cache-Control: no-store`. Docker Compose чекає `/health/ready` перед тестами.

## Готовність — 100
