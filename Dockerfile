# Сборка интерфейса
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# Сервис
FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml ./
COPY backend/ ./backend/
RUN pip install --no-cache-dir -e .

COPY data/ ./data/
COPY README.md ./
COPY docs/ ./docs/
COPY --from=ui /ui/dist ./frontend/dist

ENV PYTHONPATH=/app/backend PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "planner.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
