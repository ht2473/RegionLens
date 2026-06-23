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
            # merge_contextvars — первым: подмешивает request-scoped поля (например, request_id
            # из middleware приложения) в каждое событие; в конвейере (нет контекста) — no-op.
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.KeyValueRenderer(key_order=["event", "stage"]),
        ]
    )


log = structlog.get_logger()
