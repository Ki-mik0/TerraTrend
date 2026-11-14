.PHONY: sync api web

sync:
	uv sync

api:
	uv run uvicorn earthtrend.api.main:app --reload --app-dir src

web:
	npm --prefix web run dev
