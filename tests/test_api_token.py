"""Аутентификация по личному токену API и управление токеном в кабинете."""

from __future__ import annotations

import re
import secrets

import pytest
from core.api.authentication import ApiTokenAuthentication, hash_token
from core.models import UserProfile
from django.contrib.auth.models import User
from django.test import Client
from rest_framework.test import APIClient, APIRequestFactory

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()
_auth = ApiTokenAuthentication()


def _user_with_token(username: str = "u") -> tuple[User, str]:
    """Создать пользователя с выпущенным токеном; вернуть (user, сырой_ключ)."""
    user = User.objects.create_user(username=username, password="x")
    raw = secrets.token_urlsafe(32)
    UserProfile.objects.update_or_create(user=user, defaults={"api_token": hash_token(raw)})
    return user, raw


def test_hash_is_stable_and_not_raw() -> None:
    raw = "abc123"
    assert hash_token(raw) == hash_token(raw)
    assert hash_token(raw) != raw and len(hash_token(raw)) == 64


def test_no_authorization_header_returns_none() -> None:
    assert _auth.authenticate(_factory.get("/")) is None


def test_non_token_scheme_is_ignored() -> None:
    request = _factory.get("/", HTTP_AUTHORIZATION="Bearer something")
    assert _auth.authenticate(request) is None


def test_valid_token_authenticates_user() -> None:
    user, raw = _user_with_token()
    request = _factory.get("/", HTTP_AUTHORIZATION=f"Token {raw}")
    result = _auth.authenticate(request)
    assert result is not None and result[0] == user


def test_invalid_token_is_rejected() -> None:
    from rest_framework.exceptions import AuthenticationFailed

    request = _factory.get("/", HTTP_AUTHORIZATION="Token not-a-real-token")
    with pytest.raises(AuthenticationFailed):
        _auth.authenticate(request)


def test_empty_token_after_keyword_is_rejected() -> None:
    from rest_framework.exceptions import AuthenticationFailed

    request = _factory.get("/", HTTP_AUTHORIZATION="Token")
    with pytest.raises(AuthenticationFailed):
        _auth.authenticate(request)


def test_inactive_user_token_is_rejected() -> None:
    from rest_framework.exceptions import AuthenticationFailed

    user, raw = _user_with_token()
    user.is_active = False
    user.save(update_fields=["is_active"])
    request = _factory.get("/", HTTP_AUTHORIZATION=f"Token {raw}")
    with pytest.raises(AuthenticationFailed):
        _auth.authenticate(request)


def test_bad_token_rejected_by_api_endpoint() -> None:
    """Неверный токен на реальном эндпойнте → 401 (доказывает, что метод подключён)."""
    resp = APIClient().get("/api/v1/regions/", HTTP_AUTHORIZATION="Token nope")
    assert resp.status_code == 401


def test_cabinet_generate_stores_hash_and_shows_once() -> None:
    user = User.objects.create_user(username="cab", password="x")
    client = Client()
    client.force_login(user)

    resp = client.post("/account/api/generate/", follow=True)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Новый токен выпущен" in body

    profile = UserProfile.objects.get(user=user)
    assert len(profile.api_token) == 64  # в БД только SHA-256-хеш, не сырой ключ

    # Показанный один раз ключ действительно аутентифицирует пользователя.
    raw = re.search(r'readonly value="([^"]+)"', body).group(1)
    assert profile.api_token == hash_token(raw)
    request = _factory.get("/", HTTP_AUTHORIZATION=f"Token {raw}")
    assert _auth.authenticate(request)[0] == user

    # Повторное открытие страницы ключ уже не показывает.
    assert "Новый токен выпущен" not in client.get("/account/api/").content.decode()


def test_cabinet_revoke_clears_token() -> None:
    user, _raw = _user_with_token("revoker")
    client = Client()
    client.force_login(user)
    client.post("/account/api/revoke/")
    assert UserProfile.objects.get(user=user).api_token == ""
