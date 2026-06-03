.PHONY: install lint format type test pipeline migrate run all docker-up docker-down

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

pipeline:         ## Пересобрать всю аналитику офлайн-конвейером
	python -m pipeline.run_all

migrate:          ## Применить миграции Django
	python backend/manage.py migrate

run:              ## Запустить dev-сервер Django
	python backend/manage.py runserver

all: pipeline migrate   ## Пересборка аналитики + миграции (воспроизводимый прогон)

docker-up:        ## Поднять стек в Docker
	docker compose up -d --build

docker-down:      ## Остановить стек
	docker compose down
