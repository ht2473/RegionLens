# RegionLens

Аналитическая BI-платформа для анализа и визуализации социально-экономических
показателей регионов РФ на открытых данных Росстата.

> **Архитектура «два мира»:** офлайн-конвейер считает всю аналитику заранее и пишет в
> аналитическое хранилище (DuckDB); веб-приложение (Django + DRF) только читает готовое
> и отдаёт пользователю. Источник истины по решениям и архитектуре — `docs/00_MasterPlan.md`.

## Стек

- **Backend:** Django + Django REST Framework (сессионная аутентификация).
- **Хранение:** PostgreSQL (OLTP, операционка) + DuckDB (OLAP, аналитика, read-only из приложения).
- **Frontend:** серверный рендер (Django-шаблоны) + HTMX/Alpine.js + Plotly.js + MapLibre GL JS.
- **Аналитика/ML:** polars, scikit-learn, scipy, statsmodels/sktime, shap, mapie, ruptures, mlflow.
- **Качество:** ruff, mypy, pytest, pandera, pre-commit, DVC, drf-spectacular, Docker.

## Структура репозитория

```
regionlens/
├── main.py                 # точка входа для проверяющего (runserver)
├── requirements.txt        # зависимости для проверяющего (синхрон с pyproject)
├── pyproject.toml          # зависимости группами + ruff/mypy/pytest
├── Makefile                # install / lint / type / test / pipeline / run / all
├── docker-compose.yml      # dev: postgres + backend
├── config/                 # YAML-конфиги аналитики (метрики, домены, веса, пороги)
├── data/raw/               # сырьё (под DVC)
├── pipeline/               # офлайн-конвейер (S1–S9): расчёт аналитики -> DuckDB
│   ├── logging_setup.py    # единый structlog
│   ├── run_all.py          # оркестратор (одна команда пересборки)
│   └── ingestion/          # адаптеры источников (SourceAdapter)
├── backend/                # Django-проект
│   ├── manage.py
│   ├── config/             # settings/urls/wsgi/asgi
│   └── core/               # приложение: модели (Ф10), API (Ф6), представления
└── tests/                  # pytest
```

## Требования

Python 3.12, Git, Docker (для контейнерного запуска).

## Быстрый старт (локально)

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[pipeline,backend,dev]"             # или: make install
cp .env.example .env                                 # отредактируйте при необходимости
python backend/manage.py migrate
python backend/manage.py runserver                   # или: make run
```

Healthcheck: <http://127.0.0.1:8000/healthz/>. Админка: <http://127.0.0.1:8000/admin/>.

### Запуск как делает проверяющий

```bash
pip install -r requirements.txt
python main.py        # поднимает сервер на 0.0.0.0:8000
```

## Запуск в Docker

```bash
docker compose up -d --build      # или: make docker-up
```

Поднимает PostgreSQL и backend; приложение доступно на порту 8000.

## Офлайн-конвейер

```bash
python -m pipeline.run_all        # или: make pipeline
make all                          # пересборка аналитики + миграции
```

На Ф0 конвейер — каркас (стадии S1–S9 подключаются в Ф1–Ф9).

## Качество и тесты

```bash
make lint     # ruff check + ruff format --check
make type     # mypy
make test     # pytest
pre-commit install && pre-commit run --all-files
```

## Воспроизводимость

Сиды зафиксированы; `make all` пересобирает аналитику начисто. Данные версионируются
через DVC (`data/raw` под отслеживанием), эксперименты логируются в MLflow.

## Документация

Полный проектный комплект — в `docs/`: `00_MasterPlan.md` (Хартия), `01_Implementation_Guide.md`
(пошаговые фазы), `REFERENCE.md` (словарь данных/конфиги/API), `PROGRESS.md` (состояние).

## Статус

**Ф0 — Каркас и инфраструктура.** Далее: Ф1 (данные / ETL + гармонизация).

## Автор и лицензия

Автор: Фамилия Имя Отчество (студенческий билет № __________).
Данные: Росстат / портал «Если быть точным», лицензия **CC BY 4.0**.
Репозиторий: <ссылка на публичный репозиторий GitFlic/GitHub>.
