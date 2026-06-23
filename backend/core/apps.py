"""Конфигурация Django-приложения core."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Ядро RegionLens"

    def ready(self) -> None:
        """Подключить обработчики сигналов и единое структурное логирование.

        configure_logging() включает merge_contextvars — request_id из RequestIDMiddleware
        попадает во все записи лога приложения (сквозная трассировка запроса).
        """
        from pipeline.logging_setup import configure_logging

        configure_logging()
        from core import signals  # noqa: F401  (импорт ради регистрации обработчиков)
