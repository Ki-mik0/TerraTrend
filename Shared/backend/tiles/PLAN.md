---
domain: tiles
kind: scope
status: done
---

# tiles — що реалізувати

Тайл — читання готового `GridTrendProduct`, не новий розрахунок. Корінь `GridProduct` (метадані сітки), запит — `TileRequest`.

## Дії

- Віддати PNG 256×256 продукту `trend` або `ai_class` для `z/x/y` (Web Mercator, `z` 0–12).
- Параметри: `variable_id`, `period` (`РРРР-РРРР`), `season`, `palette` (`rdbu`, `puor`, `cividis` — безпечні для дальтоніків), `significant_only`, `year` кадру анімації.
- `trend`: розбіжна палітра на `[-vmax, vmax]`. Значуща після FDR клітинка непрозора, незначуща — бліда, а з `significant_only` — прозора. Штрихування малює фронтенд.
- `ai_class`: кольори Paul Tol для `linear`, `step`, `accelerating`, `seasonal_shift`; `none` прозорий.
- Кадр року — `anomaly_<year>` із продукту, а якщо його немає — нахил, помножений на відстань від середини періоду.
- Тайл поза межами сітки — один спільний прозорий PNG, не зберігається.
- Віддати список сіток: змінна, період, сезон, версія, межі, роки, шаблон URL.

## Маршрути

- `GET /api/v1/tiles/{product}/{z}/{x}/{y}.png?variable_id=&period=&season=&palette=&significant_only=&year=`
- `GET /api/v1/tiles/products?variable_id=`

Публічні. PNG має `ETag` і `Cache-Control: public, max-age=86400, immutable` (версія даних у ключі), на `If-None-Match` — `304`, заголовок `X-Tile-Cache: hit|miss|empty`.
Помилки: `tile_out_of_range`, `palette_invalid`, `product_invalid`, `season_invalid`, `period_invalid`, `year_invalid` → 422; `variable_not_found`, `grid_not_found` → 404.

## Продукт від аналітики

```
STORAGE_ROOT/grids/index.json   {"products": [{"variable_id", "period", "season", "version", "file",
                                               "bbox": [w, s, e, n], "resolution", "vmax", "years": [...]}]}
STORAGE_ROOT/grids/<file>.npz   slope, sig_fdr, ai_class, ai_step_prob, anomaly_<year>...
```

Рядки сітки — з півночі на південь, стовпці — із заходу на схід. Новий `index.json` підхоплюється за часом зміни, без рестарту. Без індексу — детермінований синтетичний seed (`gldas_sm`, `merra2_t2m`, `modis_ndvi`; `annual`, `JJA`; 2000–2024).

## Кеш

PNG лежить у `LocalObjectStorage` за ключем `tile/{version}/{product}/{variable}/{period}/{season}/{palette}/{sig}/{year}/{z}/{x}/{y}.png`. Масиви сіток — LRU на 8 продуктів у процесі. Метрики: `tile_requests_total{product,outcome}`, `tile_render_seconds`.

## Готовність — 100

Рендер (numpy + Pillow), обидва продукти, кадри року, палітри, сховище PNG, `ETag`/`304`, список сіток, прогрів z0–2 через `POST /admin/warm-cache`. Усе покрите тестами.
