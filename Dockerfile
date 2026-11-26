# Imagen de la API y del worker (docker-compose.yml)
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY db/migrations ./db/migrations
ENV PATH="/srv/.venv/bin:$PATH" PORT=8080
# Sin root: el código queda de root y solo se lee.
# uid fijo: el tmpfs del audio (docker-compose.yml) se monta con este dueño.
RUN useradd --system --no-create-home --uid 10001 moneymap
USER moneymap
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
