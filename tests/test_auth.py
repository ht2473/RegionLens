"""Тесты аутентификации и регистрации (Ф10·3): сигнал профиля, регистрация, вход/выход, nav.

Регистрация назначает роль viewer (группа создаётся либо setup_roles, либо get_or_create
в самой вьюхе), профиль создаётся сигналом. Проверяем happy-path и отказы формы, а также
отражение состояния входа в навигации.
"""

from __future__ import annotations

import pytest
from core.models import UserProfile
from core.permissions import ROLE_VIEWER
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

_PW = "Sl0transit-9"  # проходит валидаторы пароля (длина/не общий/не числовой)


@pytest.fixture
def roles() -> None:
    call_command("setup_roles")


def test_profile_created_by_signal() -> None:
    """Сигнал создаёт профиль для любого нового пользователя (без явного создания)."""
    u = User.objects.create_user("solo", password=_PW)
    assert UserProfile.objects.filter(user=u).exists()
    assert u.profile is not None


def test_register_page_renders(client: Client) -> None:
    """Страница регистрации доступна анониму (200) и содержит заголовок."""
    resp = client.get(reverse("register"))
    assert resp.status_code == 200
    assert "Регистрация" in resp.content.decode()


def test_register_creates_user_with_viewer_role(client: Client, roles: None) -> None:
    """Успешная регистрация создаёт пользователя, роль viewer, профиль и выполняет вход."""
    resp = client.post(
        reverse("register"),
        {"username": "newbie", "email": "n@example.com", "password1": _PW, "password2": _PW},
    )
    assert resp.status_code == 302  # редирект на главную после входа
    u = User.objects.get(username="newbie")
    assert u.groups.filter(name=ROLE_VIEWER).exists()
    assert UserProfile.objects.filter(user=u).exists()
    assert resp.wsgi_request.user.is_authenticated


def test_register_rejects_duplicate_username(client: Client, roles: None) -> None:
    """Занятое имя пользователя отклоняется формой (200, без создания второго)."""
    User.objects.create_user("taken", password=_PW)
    resp = client.post(
        reverse("register"),
        {"username": "taken", "password1": _PW, "password2": _PW},
    )
    assert resp.status_code == 200
    assert User.objects.filter(username="taken").count() == 1


def test_register_rejects_password_mismatch(client: Client) -> None:
    """Несовпадение паролей отклоняется (пользователь не создан)."""
    resp = client.post(
        reverse("register"),
        {"username": "mismatch", "password1": _PW, "password2": "Different-9"},
    )
    assert resp.status_code == 200
    assert not User.objects.filter(username="mismatch").exists()


def test_login_logout_flow(client: Client) -> None:
    """Вход по форме аутентифицирует; выход (POST) разлогинивает с редиректом."""
    User.objects.create_user("loginme", password=_PW)
    resp = client.post(reverse("login"), {"username": "loginme", "password": _PW})
    assert resp.status_code == 302
    assert resp.wsgi_request.user.is_authenticated
    resp = client.post(reverse("logout"))
    assert resp.status_code == 302


def test_authenticated_register_redirects(client: Client) -> None:
    """Уже вошедший пользователь со страницы регистрации уходит на главную."""
    User.objects.create_user("already", password=_PW)
    client.login(username="already", password=_PW)
    resp = client.get(reverse("register"))
    assert resp.status_code == 302


def test_nav_shows_auth_links_for_anonymous(client: Client) -> None:
    """В навигации анонима — ссылки «Войти» и «Регистрация»."""
    html = client.get(reverse("home")).content.decode()
    assert "Войти" in html
    assert "Регистрация" in html


def test_nav_shows_username_when_authenticated(client: Client) -> None:
    """В навигации вошедшего — его имя и кнопка «Выйти»."""
    User.objects.create_user("navuser", password=_PW)
    client.login(username="navuser", password=_PW)
    html = client.get(reverse("home")).content.decode()
    assert "navuser" in html
    assert "Выйти" in html


def test_register_rejects_username_with_symbols(client: Client) -> None:
    """Имя пользователя с символами/дефисом отклоняется (только буквы и цифры)."""
    resp = client.post(
        reverse("register"),
        {"username": "bad-name!", "password1": _PW, "password2": _PW},
    )
    assert resp.status_code == 200
    assert not User.objects.filter(username="bad-name!").exists()


def test_register_accepts_cyrillic_alphanumeric(client: Client, roles: None) -> None:
    """Имя из кириллицы и цифр допустимо (буквы латиница/кириллица + цифры)."""
    resp = client.post(
        reverse("register"),
        {"username": "Евгений2025", "password1": _PW, "password2": _PW},
    )
    assert resp.status_code == 302
    assert User.objects.filter(username="Евгений2025").exists()


def test_register_rejects_username_over_40(client: Client) -> None:
    """Имя длиннее 40 символов отклоняется."""
    long_name = "a" * 41
    resp = client.post(
        reverse("register"),
        {"username": long_name, "password1": _PW, "password2": _PW},
    )
    assert resp.status_code == 200
    assert not User.objects.filter(username=long_name).exists()
