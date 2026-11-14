.PHONY: sync api web test test-fast lint calibrate coverage bench

sync:
	uv sync

api:
	uv run uvicorn earthtrend.api.main:app --reload --app-dir src

web:
	npm --prefix web run dev

test:
	uv run pytest testscd /d/NASA/TerraTrend && .venv/Scripts/python -m pytest tests -m "not slow" -q

test-fast:
	uv run pytest tests -m "not slow"

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy src/earthtrend/analytics

# Stage 4: re-run whenever a verdict threshold or rule changes (the gate test enforces it).
calibrate:
	uv run --group docs python -m earthtrend.analytics.validation.calibrate

# PLAN_ANALYTICS 16: >= 90% for trend/, evidence/, spatial/. numba code is only visible to
# coverage with the JIT disabled.
coverage:
	NUMBA_DISABLE_JIT=1 uv run pytest tests/analytics -m "not slow" 		--cov=src/earthtrend/analytics/trend --cov=src/earthtrend/analytics/evidence 		--cov=src/earthtrend/analytics/spatial --cov-fail-under=90

# PLAN_ANALYTICS 14: targets asserted in the tests; > 20% regression vs the saved baseline fails.
bench:
	uv run pytest tests/analytics/benchmarks --benchmark-autosave 		--benchmark-compare --benchmark-compare-fail=median:20%
