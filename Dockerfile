# Сборка интерфейса
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# Сервис
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

# Зависимости строго по uv.lock, отдельным слоем
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Проект ставится в режиме editable: paths.py ищет data/ и runtime/ относительно исходников
COPY pyproject.toml uv.lock ./
COPY backend/ ./backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

COPY data/ ./data/
COPY README.md ./
COPY docs/ ./docs/
COPY --from=ui /ui/dist ./frontend/dist

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "planner.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
