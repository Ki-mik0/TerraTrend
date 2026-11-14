FROM python:3.12-slim AS runtime

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
    DB_URL="postgresql+asyncpg://earthtrend:earthtrend@db:5432/earthtrend" \
    REDIS_URL="redis://cache:6379/0" \
    STORAGE_ROOT="/data/storage" \
    CATALOG_DIR="/app/catalog" \
    MODELS_DIR="/models"

VOLUME ["/data", "/models"]
EXPOSE 8000

CMD ["uvicorn", "earthtrend.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test

RUN uv sync --extra dev
COPY tests ./tests
