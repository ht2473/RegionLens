"""Тесты команды `seed_demo`: демо-пользователи трёх ролей, флаги доступа, пароли,
идемпотентность, переопределение пароля и минимальный контент кабинета.

Команда должна поднимать приложение «из коробки»: создавать учётки viewer/analyst/admin,
выдавать администратору доступ к админ-панели и не плодить дубликаты при повторном запуске.
"""

from __future__ import annotations

import pytest
from core.models import SavedView
from core.permissions import ROLE_ADMIN, ROLE_ANALYST, ROLE_VIEWER
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.management import call_command

pytestmark = pytest.mark.django_db

_DEMO_LOGINS = {"demo_viewer": ROLE_VIEWER, "demo_analyst": ROLE_ANALYST, "demo_admin": ROLE_ADMIN}


def test_creates_three_demo_users_in_correct_roles() -> None:
    """Команда создаёт трёх демо-пользователей, каждый — в своей группе-роли."""
    call_command("seed_demo")
    for login, role in _DEMO_LOGINS.items():
        user = User.objects.get(username=login)
        assert list(user.groups.values_list("name", flat=True)) == [role]


def test_admin_can_access_admin_panel_others_cannot() -> None:
    """Только demo_admin получает доступ к админ-панели (is_staff/is_superuser)."""
    call_command("seed_demo")
    assert User.objects.get(username="demo_admin").is_staff
    assert User.objects.get(username="demo_admin").is_superuser
    assert not User.objects.get(username="demo_viewer").is_staff
    assert not User.objects.get(username="demo_analyst").is_staff


def test_default_passwords_authenticate() -> None:
    """Пароли по умолчанию действительны для аутентификации."""
    call_command("seed_demo")
    assert authenticate(username="demo_viewer", password="viewer-demo-2025") is not None
    assert authenticate(username="demo_analyst", password="analyst-demo-2025") is not None
    assert authenticate(username="demo_admin", password="admin-demo-2025") is not None


def test_password_override_applies_to_all() -> None:
    """Опция --password задаёт единый пароль для всех демо-учёток."""
    call_command("seed_demo", password="shared-secret-1")
    for login in _DEMO_LOGINS:
        assert authenticate(username=login, password="shared-secret-1") is not None


def test_idempotent_no_duplicates() -> None:
    """Повторный запуск не плодит пользователей и сохранённые виды."""
    call_command("seed_demo")
    call_command("seed_demo")
    assert User.objects.filter(username__in=_DEMO_LOGINS).count() == 3
    # По одному демо-виду для viewer и analyst, без дублей.
    assert SavedView.objects.filter(name="Пример: рейтинг развития, 2024").count() == 2


def test_seeds_minimal_cabinet_content() -> None:
    """Для viewer и analyst создаётся демонстрационный сохранённый вид."""
    call_command("seed_demo")
    for login in ("demo_viewer", "demo_analyst"):
        user = User.objects.get(username=login)
        assert SavedView.objects.filter(user=user).exists()
