.PHONY: sync api web test test-fast lint calibrate coverage bench contract contract-check contract-watch hooks

sync:
	uv sync

api:
	uv run uvicorn earthtrend.api.main:create_app --factory --reload --app-dir src

web:
	npm --prefix web run dev

test:
	uv run pytest tests -m "not slow" -q

test-fast:
	uv run pytest tests -m "not slow"

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy src/earthtrend/analytics

calibrate:
	uv run --group docs python -m earthtrend.analytics.validation.calibrate

coverage:
	NUMBA_DISABLE_JIT=1 uv run pytest tests/analytics -m "not slow" \
		--cov=src/earthtrend/analytics/trend --cov=src/earthtrend/analytics/evidence \
		--cov=src/earthtrend/analytics/spatial --cov-fail-under=90

bench:
	uv run pytest tests/analytics/benchmarks --benchmark-autosave \
		--benchmark-compare --benchmark-compare-fail=median:20%

contract:
	uv run python scripts/contract.py --web

contract-check:
	uv run python scripts/contract.py --check
	npm --prefix web run api:check
	npm --prefix web run typecheck

contract-watch:
	uv run python scripts/contract.py --watch

hooks:
	git config core.hooksPath .githooks
