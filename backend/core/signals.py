"""Сигналы приложения core.

- Авто-создание операционного профиля при появлении пользователя: каждому `User`
  гарантированно сопоставляется `UserProfile` (на это рассчитывает кабинет).
- Аудит входа/выхода: сигналы auth пишут событие в журнал.
Подключается в `CoreConfig.ready()`.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import HttpRequest

from core.audit import record
from core.models import UserProfile


@receiver(post_save, sender=User)
def ensure_user_profile(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    """Создать профиль для нового пользователя (идемпотентно)."""
    if created:
        UserProfile.objects.get_or_create(user=instance)


@receiver(user_logged_in)
def log_login(sender: object, request: HttpRequest, user: User, **kwargs: Any) -> None:
    """Записать вход пользователя в журнал аудита."""
    record(user, "auth:login")


@receiver(user_logged_out)
def log_logout(sender: object, request: HttpRequest, user: User | None, **kwargs: Any) -> None:
    """Записать выход пользователя в журнал аудита."""
    record(user, "auth:logout")
