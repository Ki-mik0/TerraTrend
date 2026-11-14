---
domain: cache
kind: scope
status: done
---

# cache — що реалізувати

Спільний `CachePort` (`application/shared/cache.py`) для всіх зон. Значення — JSON. Збій Redis — це промах, не аварія.

## Як влаштовано

- `cache_from_env()`: Redis за `REDIS_URL`, інакше словник із TTL у процесі. Обгортка `MeteredCache` рахує влучання, промахи й збої за родиною ключа.
- Один клієнт Redis і один пул з'єднань на процес (`shared_redis`). `main.py` створює один екземпляр кешу й передає його каталогу, справам, освіті, радару й історіям.
- Байти тайлів лежать у `LocalObjectStorage` (`STORAGE_ROOT`), запис атомарний, ключі без `..`.
- Версія даних входить у ключ, тож новий продукт робить старі записи недосяжними без явного скидання.

## Родини ключів

| Родина | Хто пише | Приклад |
|---|---|---|
| `catalog` | каталог | `catalog:v{generation}:var:{id}` |
| `case` | справи | `case:{sha256(spec + версії)}` |
| `story` | Story Lens | `story:v1:{var}:{region}:...` |
| `edu` | освіта | `edu:demos:{generation}:{lang}` |
| `radar` | радар | `radar:feed:{version}:...` |
| `assistant` | асистент | `assistant:plan:...` |
| `tile` | тайли (файли) | `tile/{version}/...png` |

## Адмін-дії

- `GET /api/v1/admin/cache` — бекенд, доступність, влучання/промахи/збої і частка влучань за родинами.
- `POST /api/v1/admin/warm-cache` — прогріває перші сторінки всіх стрічок радару й типологію, демо, словник і вікторини обома мовами, тайли z0–2 усіх сіток. Збій одного прогрівача не зупиняє інших.
- `DELETE /api/v1/admin/cache?family=` — скидає родину або `all`.

Лише роль `admin`. Кожна дія пише рядок `audit_logs` (`warm_cache`, `clear_cache`; міграція `008_admin_audit`).

## Метрики

`GET /metrics` (Prometheus): `http_requests_total`, `http_request_duration_seconds`, `cache_hits_total`, `cache_misses_total`, `cache_errors_total`, `tile_requests_total`, `tile_render_seconds`. Шляхи `/health` і `/metrics` не рахуються.

## Готовність — 100
