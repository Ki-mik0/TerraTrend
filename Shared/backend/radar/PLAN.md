---
domain: radar
kind: scope
status: done
---

# radar — що реалізувати

Корінь `RadarItem`. Стрічка — вибірка цих записів, не сутність. `TypologyCluster` — читання радару, не корінь. `RadarProduct` — один запуск сканування аналітики з версією.

## Дії

- Віддати сторінку стрічки. Фільтри: `feed`, змінна, регіон, сезон, сторінка. Сортування за `score` спадно.
- Дозволені стрічки: `strongest`, `opposite`, `accelerating`, `breakpoints`, `almost`, `stable`, `ai_flagged`.
- Картка: напрям, нахили, SNR, p, q FDR, прапор розколу, оцінка, рівень вироку, сезон, новизна (`new`, `upgraded`, `downgraded`, `unchanged`), `years_to_detect`, площа, URL справи.
- Сторінка підписана як «статистичні кандидати після поправки FDR» (`label`, `lang=uk|en`) і несе `total`, `data_version`, `generated_at`.
- Віддати типологію схожих змін з фільтром за змінними і сезоном.
- Підхопити новий продукт після нових місячних даних без рестарту.

Бекенд рядки радару не перераховує. Він лише відкидає рядок, що суперечить правилу стрічки з `PLAN_ANALYTICS` §9.4:

| Стрічка | Правило |
|---|---|
| `strongest` | `proven` або `strong` |
| `almost` | `suspicious` і `years_to_detect` ≤ 10 |
| `stable` | `no_evidence` |
| `opposite` | `split_flag` або значущий вирок |
| `ai_flagged` | не `no_evidence` і не `inadmissible` |
| `accelerating`, `breakpoints` | значущий вирок (`proven`, `strong`, `likely`) |

## Маршрути

- `GET /api/v1/radar?feed=&variable_id=&region_id=&season=&page=&page_size=&lang=`
- `GET /api/v1/radar/typology?variables=a,b&season=`

Обидва публічні, з `ETag` і `Cache-Control: public, max-age=300`. На `If-None-Match` відповідають `304`. Помилки `feed_invalid`, `page_invalid` (сторінка ≥ 1, розмір 1–100), `season_invalid` дають 422.

## Продукт від аналітики

Аналітика пише файли в `STORAGE_ROOT/radar/`:

```
latest.json      {"version": "2026-11"}
2026-11.json     {"version", "generated_at", "items": [RadarItem...], "clusters": [TypologyCluster...]}
```

Поля рядка — як у `domain/radar/model.py` (`RadarItem`, `TypologyCluster`). Новий місячний запуск пише новий файл версії, потім підміняє `latest.json`. Рядок, що порушує правило, пропускається з попередженням у лозі. Без `latest.json` бекенд віддає вбудований seed (`infrastructure/radar/seed.py`).

## Кеш

`CachePort`: Redis за `REDIS_URL`, інакше пам’ять. Збій Redis — промах.

| Ключ | Що | TTL |
|---|---|---|
| `radar:version` | остання версія продукту | 60 с — нова версія видна за хвилину |
| `radar:feed:{version}:{feed}:{var}:{region}:{season}:{page}:{size}` | сторінка | 1 год |
| `radar:typology:{version}:{season}:{vars}` | кластери | 1 год |

Версія входить у ключ, тож новий продукт робить старі сторінки недосяжними без явного скидання.

## Не входить

Перевірка живності, PNG-тайли, прогрів кешу. Саме сканування і правила оцінки — аналітика (`analytics/radar`).

## Готовність — 100

Стрічки з метаданими й підписом FDR, типологія, версійний продукт із файлів аналітики, оновлення без рестарту, перевірка правил стрічок, кеш у Redis і HTTP `ETag`. Усе покрите тестами.
