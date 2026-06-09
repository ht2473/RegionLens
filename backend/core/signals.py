"""Сигналы приложения core (Ф10·3).

Авто-создание операционного профиля при появлении пользователя: каждому `User`
(зарегистрированному через форму, заведённому в админке или командой createsuperuser)
гарантированно сопоставляется `UserProfile`. На это рассчитывает личный кабинет (Ф10·5).
Подключается в `CoreConfig.ready()`.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import UserProfile


@receiver(post_save, sender=User)
def ensure_user_profile(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    """Создать профиль для нового пользователя (идемпотентно)."""
    if created:
        UserProfile.objects.get_or_create(user=instance)
