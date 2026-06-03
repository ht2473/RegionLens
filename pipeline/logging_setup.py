"""Единая настройка структурного логирования (structlog) для всего конвейера."""
import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Настроить логирование: уровень, ISO-таймстемпы, рендер вида key=value.

    Параметры:
        level: уровень логирования ("DEBUG" / "INFO" / "WARNING" / ...).
    Побочные эффекты:
        Глобально конфигурирует стандартный logging и процессоры structlog.
    """
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.KeyValueRenderer(key_order=["event", "stage"]),
        ]
    )


log = structlog.get_logger()
