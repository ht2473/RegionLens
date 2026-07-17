# backend/Dockerfile — dev-образ backend RegionLens. Прод-сборка — multi-stage.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH="/app:/app/backend"

WORKDIR /app

# Системные зависимости: psycopg/сборка колёс + weasyprint (pango/cairo/gdk-pixbuf)
# и кириллический шрифт DejaVu для PDF-экспорта отчёта региона.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
        libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libcairo2 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Сначала зависимости (кэш слоёв), затем код (в dev код монтируется томом из compose).
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["python", "backend/manage.py", "runserver", "0.0.0.0:8000"]
