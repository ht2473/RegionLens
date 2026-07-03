"""Журналирование действий.

Единая точка записи ключевых операционных событий в `AuditLog`: вход/выход (сигналы auth),
регистрация, экспорт отчёта, создание/удаление сохранённого вида, обратная связь. Действия
от анонимных пользователей пишутся без ссылки на пользователя (`user=None`).
"""

from __future__ import annotations

from django.contrib.auth.models import AnonymousUser, User

from core.models import AuditLog


def record(user: User | AnonymousUser | None, action: str) -> None:
    """Записать действие в журнал аудита.

    Аноним или `None` сохраняются как запись без пользователя; текст действия усекается до
    лимита поля (120 символов).
    """
    actor = user if (user is not None and user.is_authenticated) else None
    AuditLog.objects.create(user=actor, action=action[:120])
