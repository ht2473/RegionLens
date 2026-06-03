#!/usr/bin/env python
"""Утилита командной строки Django (manage.py)."""

import os
import sys


def main() -> None:
    """Точка входа административных команд Django."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            'Не найден Django. Установите зависимости: pip install -e ".[backend,dev]".'
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
