# Dockerfile de production deedbook API
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Installation des dépendances avec uv
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

ADD . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.13-slim-bookworm

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Exécution sous utilisateur non-privilégié
RUN useradd -u 1000 -U -M deedbook \
    && mkdir -p /var/lib/deedbook \
    && chown -R deedbook:deedbook /var/lib/deedbook

COPY --from=builder /app /app

USER deedbook

EXPOSE 8000
CMD ["uvicorn", "deedbook.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
