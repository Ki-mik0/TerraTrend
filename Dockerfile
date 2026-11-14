FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY catalog ./catalog
COPY alembic.ini ./
COPY alembic ./alembic

RUN uv sync --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    DB_URL="sqlite+aiosqlite:///data/app.db" \
    STORAGE_ROOT="/data/storage" \
    CATALOG_DIR="/app/catalog" \
    MODELS_DIR="/models"

VOLUME ["/data", "/models"]
EXPOSE 8000

CMD ["python", "-c", "import earthtrend, earthtrend.analytics, earthtrend.api; print('earthtrend image ready')"]
