.PHONY: install lint format type test js-test audit load pipeline migrate seed bootstrap run all docker-up docker-down

install:          ## Установить проект и все группы зависимостей
	pip install -e ".[pipeline,backend,dev]"

lint:             ## Проверить стиль (ruff)
	ruff check .
	ruff format --check .

format:           ## Автоформат и автофиксы (ruff)
	ruff format .
	ruff check --fix .

type:             ## Проверить типы (mypy)
	mypy pipeline backend

test:             ## Прогнать тесты (pytest)
	pytest

e2e:              ## Браузерные сценарии Playwright (первый запуск скачает chromium)
	python -m playwright install chromium
	pytest tests/e2e -m e2e

js-test:          ## Юнит-тесты клиентского JS (vitest; нужен Node и `npm ci`)
	npm test

pipeline:         ## Пересобрать всю аналитику офлайн-конвейером
	python -m pipeline.run_all

refresh:          ## Обновить витрину из выгрузки: make refresh SRC=путь/к/файлу.parquet
	python backend/manage.py refresh_data --source $(SRC)

migrate:          ## Применить миграции Django
	python backend/manage.py migrate

seed:             ## Демо-данные: роли + пользователи viewer/analyst/admin + контент
	python backend/manage.py seed_demo

bootstrap: install migrate seed  ## Запуск «из коробки»: установка → миграции → демо-данные → проверка
	python backend/manage.py check

run:              ## Запустить dev-сервер Django
	python backend/manage.py runserver

all: pipeline migrate   ## Пересборка аналитики + миграции (воспроизводимый прогон)

docker-up:        ## Поднять стек в Docker
	docker compose up -d --build

docker-down:      ## Остановить стек
	docker compose down

audit:            ## Аудит зависимостей на уязвимости (pip-audit; diskcache CVE-2025-69872 — без фикса, подавлен)
	pip-audit -r requirements.txt --no-deps --ignore-vuln CVE-2025-69872

load:             ## Нагрузочный замер locust (нужен поднятый сервер :8000 и DuckDB)
	locust -f tests/load/locustfile.py --host http://127.0.0.1:8000
