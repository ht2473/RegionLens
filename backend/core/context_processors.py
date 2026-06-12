"""Контекст-процессор ролей: прокидывает эффективные роли пользователя в шаблоны.

Нужен для гейтинга пунктов меню по роли (напр. «Аномалии» — только analyst). Роли
вычисляются единым `effective_roles` (иерархия viewer ⊂ analyst ⊂ admin, суперпользователь).
"""

from __future__ import annotations

from django.http import HttpRequest

from .permissions import ROLE_ADMIN, ROLE_ANALYST, effective_roles


def user_roles(request: HttpRequest) -> dict[str, object]:
    """Добавляет в контекст шаблонов набор ролей и удобные флаги is_analyst/is_app_admin."""
    user = getattr(request, "user", None)
    roles: set[str] = effective_roles(user) if user is not None else set()
    return {
        "user_roles": roles,
        "is_analyst": ROLE_ANALYST in roles,
        "is_app_admin": ROLE_ADMIN in roles,
    }
