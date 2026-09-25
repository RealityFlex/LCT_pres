# Лекало: один образ — API + собранный фронтенд + LibreOffice для рендера.
# Сборка:  docker compose build     Запуск:  docker compose up

# ---------- 1. фронтенд
FROM node:20-bookworm-slim AS web
WORKDIR /web
# lock-файл собран на Windows: из-за бага npm (npm/cli#4828) нативные модули rolldown/tailwind/lightningcss
# для Linux по нему не ставятся — в контейнере разрешаем зависимости заново по диапазонам package.json
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. бэкенд
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
    DATA_DIR=/app/data SOFFICE_PATH=/usr/bin/soffice
# LibreOffice (рендер PPTX→PDF), fontconfig (регистрация шрифтов шаблона), базовые шрифты с кириллицей
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-impress fontconfig fonts-dejavu fonts-liberation fonts-crosextra-carlito \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY config.yaml ./
COPY examples/ examples/
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
RUN mkdir -p /app/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["python", "-m", "uvicorn", "app.api.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
