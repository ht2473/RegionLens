"""Аутентификация по личному токену API.

Клиент передаёт ключ в заголовке `Authorization: Token <ключ>`. В базе хранится только
SHA-256-хеш ключа (`UserProfile.api_token`), поэтому при проверке хешируем предъявленный
ключ и ищем совпадение. Метод сосуществует с сессионной аутентификацией: для браузера
работает сессия, для программного доступа — токен (без cookies/CSRF).
"""

from __future__ import annotations

import hashlib

from django.contrib.auth.models import User
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import authentication, exceptions
from rest_framework.request import Request

from ..models import UserProfile

_KEYWORD = "Token"


def hash_token(raw: str) -> str:
    """SHA-256-хеш ключа в hex (то, что хранится в БД)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ApiTokenAuthentication(authentication.BaseAuthentication):
    """Аутентификация по заголовку `Authorization: Token <ключ>` (хеш сверяется с БД)."""

    keyword = _KEYWORD

    def authenticate(self, request: Request) -> tuple[User, None] | None:
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None  # не наш способ — пусть пробуют другие аутентификаторы
        if len(header) == 1:
            raise exceptions.AuthenticationFailed("Некорректный заголовок: отсутствует токен.")
        if len(header) > 2:
            raise exceptions.AuthenticationFailed(
                "Некорректный заголовок: лишние пробелы в токене."
            )
        try:
            raw = header[1].decode("utf-8")
        except UnicodeError as exc:
            raise exceptions.AuthenticationFailed("Некорректный токен.") from exc

        token_hash = hash_token(raw)
        profile = UserProfile.objects.filter(api_token=token_hash).select_related("user").first()
        if profile is None:
            raise exceptions.AuthenticationFailed("Недействительный токен.")
        if not profile.user.is_active:
            raise exceptions.AuthenticationFailed("Учётная запись отключена.")
        return (profile.user, None)

    def authenticate_header(self, request: Request) -> str:
        return self.keyword


class ApiTokenScheme(OpenApiAuthenticationExtension):
    """Описание способа аутентификации по токену для OpenAPI (drf-spectacular).

    Регистрируется автоматически при импорте модуля (модуль импортируется через
    DEFAULT_AUTHENTICATION_CLASSES). Без неё генератор схемы не знает, как задокументировать
    `ApiTokenAuthentication`, и предупреждает на каждый эндпойнт.
    """

    target_class = "core.api.authentication.ApiTokenAuthentication"
    name = "ApiTokenAuth"

    def get_security_definition(self, auto_schema: object) -> dict[str, str]:
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "Личный токен доступа. Заголовок: `Authorization: Token <ключ>`.",
        }
