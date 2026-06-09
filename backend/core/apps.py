"""Конфигурация Django-приложения core."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Ядро RegionLens"

    def ready(self) -> None:
        """Подключить обработчики сигналов (авто-создание профиля пользователя)."""
        from core import signals  # noqa: F401  (импорт ради регистрации обработчиков)
