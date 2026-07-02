"""Аутентификация по личному токену API (заголовок Authorization: Token <token>).

Дополняет сессионную аутентификацию: программный клиент обращается к API по личному
ключу из личного кабинета. Read-эндпойнты открыты, но токен идентифицирует пользователя —
это задел под персональные и защищённые сценарии и «логичное завершение» кабинета.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework import authentication, exceptions

from ..models import UserProfile

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from rest_framework.request import Request


class ProfileTokenAuthentication(authentication.BaseAuthentication):
    """Аутентификация по токену из UserProfile.api_token."""

    keyword = "Token"

    def authenticate(self, request: Request) -> tuple[User, str] | None:
        """Проверить заголовок Authorization: Token <token>; вернуть (пользователь, токен)."""
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Некорректный заголовок токена API.")
        token = header[1].decode()
        if not token:
            raise exceptions.AuthenticationFailed("Пустой токен API.")
        profile = UserProfile.objects.filter(api_token=token).select_related("user").first()
        if profile is None:
            raise exceptions.AuthenticationFailed("Недействительный токен API.")
        return (profile.user, token)

    def authenticate_header(self, request: Request) -> str:
        """Значение заголовка WWW-Authenticate для ответов 401."""
        return self.keyword
