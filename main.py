# Автор: Кузьмин Евгений Олегович (студенческий билет № 70232275).
"""RegionLens — точка входа веб-приложения (Django runserver).

Запуск:
    pip install -r requirements.txt
    python main.py

Адрес и порт переопределяются переменной окружения REGIONLENS_ADDRPORT.
"""

import os
import sys
from pathlib import Path


def main() -> None:
    """Запустить веб-приложение RegionLens (Django runserver)."""
    root = Path(__file__).resolve().parent
    backend = root / "backend"
    # Делает пакеты config (проект) и core (приложение) импортируемыми.
    sys.path.insert(0, str(backend))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    addrport = os.environ.get("REGIONLENS_ADDRPORT", "0.0.0.0:8000")

    from django.core.management import execute_from_command_line

    execute_from_command_line(["manage.py", "runserver", addrport])


if __name__ == "__main__":
    main()
