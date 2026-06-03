# Автор ВКР: Фамилия Имя Отчество (студенческий билет № __________).
"""RegionLens — точка входа для проверяющего.

Поднимает веб-приложение (Django runserver). Проверяющий выполняет:
    pip install -r requirements.txt
    python main.py
Адрес и порт можно переопределить переменной окружения REGIONLENS_ADDRPORT.
"""
import os
import sys
from pathlib import Path


def main() -> None:
    """Запустить веб-приложение RegionLens (Django runserver)."""
    root = Path(__file__).resolve().parent
    backend = root / "backend"
    # Делаем пакет Django-проекта (config) и приложение (core) импортируемыми.
    sys.path.insert(0, str(backend))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    addrport = os.environ.get("REGIONLENS_ADDRPORT", "0.0.0.0:8000")

    from django.core.management import execute_from_command_line

    execute_from_command_line(["manage.py", "runserver", addrport])


if __name__ == "__main__":
    main()
