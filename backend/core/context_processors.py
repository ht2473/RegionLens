"""Контекст-процессор ролей: прокидывает эффективные роли пользователя в шаблоны.

Нужен для гейтинга пунктов меню по роли (напр. «Аномалии» — только analyst). Роли
вычисляются единым `effective_roles` (иерархия viewer ⊂ analyst ⊂ admin, суперпользователь).
"""

from __future__ import annotations

from django.http import HttpRequest

from .models import UserProfile
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


# ── Предпочтения отображения: дефолтные год/схема/мера в каждый шаблон (window.RL_PREFS) ──
_PREF_DEFAULTS: dict[str, object] = {"year": 2024, "scheme": "equal", "measure": "cluster"}


def user_preferences(request: HttpRequest) -> dict[str, object]:
    """Вернуть предпочтения отображения текущего пользователя (или значения по умолчанию).

    Прокидывает `prefs` (год/схема/мера) во все шаблоны; аналитические страницы берут их
    как начальные значения контролов через глобальный `window.RL_PREFS`. URL-параметр на
    странице всегда важнее предпочтения (deep-link не ломается). Для анонимов и при
    отсутствии профиля — значения по умолчанию.
    """
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        profile = UserProfile.objects.filter(user=user).first()
        if profile is not None:
            return {
                "prefs": {
                    "year": profile.default_year,
                    "scheme": profile.default_scheme,
                    "measure": profile.default_measure,
                }
            }
    return {"prefs": dict(_PREF_DEFAULTS)}
