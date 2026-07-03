"""Роли и контроль доступа (Ф10·2).

Роли проекта реализованы штатными Django `Group` с иерархией
**viewer ⊂ analyst ⊂ admin**: вышестоящая роль включает доступы нижестоящих. Группы и их
права создаёт идемпотентная команда `setup_roles`.

Здесь — единые имена ролей, помощник проверки членства (с учётом иерархии и
суперпользователя), классы доступа DRF для эндпойнтов и декоратор для серверных страниц.
Сами приватные поверхности (кабинет, операционные эндпойнты, расширенная аналитика)
закрываются этими средствами по мере появления в модулях Ф10·5–6 / Ф8 / Ф9 / Ф11.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.contrib.auth.models import AnonymousUser, User
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

ROLE_VIEWER = "viewer"
ROLE_ANALYST = "analyst"
ROLE_ADMIN = "admin"
ALL_ROLES: tuple[str, ...] = (ROLE_VIEWER, ROLE_ANALYST, ROLE_ADMIN)

# Иерархия ролей: ключ «включает» доступы перечисленных значений.
_ROLE_IMPLIES: dict[str, set[str]] = {
    ROLE_VIEWER: {ROLE_VIEWER},
    ROLE_ANALYST: {ROLE_VIEWER, ROLE_ANALYST},
    ROLE_ADMIN: {ROLE_VIEWER, ROLE_ANALYST, ROLE_ADMIN},
}


def effective_roles(user: User | AnonymousUser) -> set[str]:
    """Эффективные роли пользователя с учётом иерархии и суперпользователя.

    Аноним → пусто; суперпользователь → все роли; иначе — объединение раскрытых по
    иерархии групп пользователя, пересечённое с известными ролями проекта.
    """
    if not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(ALL_ROLES)
    names = set(user.groups.values_list("name", flat=True)) & set(ALL_ROLES)
    effective: set[str] = set()
    for name in names:
        effective |= _ROLE_IMPLIES.get(name, {name})
    return effective


def user_in_role(user: User | AnonymousUser, *roles: str) -> bool:
    """True, если у пользователя есть хотя бы одна из требуемых ролей (с учётом иерархии).

    Без аргументов `roles` достаточно любой известной роли (любой участник с назначенной
    ролью проходит проверку).
    """
    required = set(roles) if roles else set(ALL_ROLES)
    return bool(effective_roles(user) & required)


class _RolePermission(BasePermission):
    """База для DRF-классов доступа по роли. Конкретные классы задают набор `roles`."""

    roles: tuple[str, ...] = ()

    def has_permission(self, request: Request, view: APIView) -> bool:
        return user_in_role(request.user, *self.roles)


class IsViewer(_RolePermission):
    """Доступ для роли viewer и выше (любой участник с назначенной ролью)."""

    roles = (ROLE_VIEWER,)


class IsAnalyst(_RolePermission):
    """Доступ для роли analyst и выше (расширенная аналитика)."""

    roles = (ROLE_ANALYST,)


class IsAppAdmin(_RolePermission):
    """Доступ только для роли admin (операционное управление)."""

    roles = (ROLE_ADMIN,)


ViewFunc = Callable[..., HttpResponse]


def role_required(*roles: str) -> Callable[[ViewFunc], ViewFunc]:
    """Декоратор серверной страницы: требует одну из ролей (с учётом иерархии).

    Неаутентифицированного перенаправляет на страницу входа (302 → LOGIN_URL);
    аутентифицированного без нужной роли отклоняет (403 PermissionDenied).
    """

    def decorator(view: ViewFunc) -> ViewFunc:
        @wraps(view)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not user_in_role(user, *roles):
                raise PermissionDenied("Недостаточно прав для доступа к этой странице.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
