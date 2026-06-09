"""Тесты ролей и контроля доступа (Ф10·2): setup_roles, иерархия, DRF-классы, декоратор.

Роли создаются командой setup_roles (фикстура `roles`). Проверяем: появление трёх групп
и идемпотентность; различие наборов прав (admin ⊃ viewer); иерархию viewer ⊂ analyst ⊂ admin
с особыми случаями (аноним/суперпользователь); классы доступа DRF; декоратор страниц
(редирект анонима, 403 при нехватке роли, 200 при достаточной).
"""

from __future__ import annotations

import pytest
from core.permissions import (
    ALL_ROLES,
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_VIEWER,
    IsAnalyst,
    IsAppAdmin,
    IsViewer,
    effective_roles,
    role_required,
    user_in_role,
)
from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
from rest_framework.test import APIRequestFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def roles() -> None:
    """Создать роли через штатную команду перед тестом."""
    call_command("setup_roles")


def _user_in(group_name: str) -> User:
    """Завести пользователя и включить его в указанную группу-роль."""
    user = User.objects.create_user(username=f"u_{group_name}", password="pw-12345")
    user.groups.add(Group.objects.get(name=group_name))
    return user


def _drf_request(user: object) -> HttpRequest:
    """GET-запрос DRF с подставленным пользователем (для проверки классов доступа)."""
    request = APIRequestFactory().get("/api/x/")
    request.user = user  # type: ignore[attr-defined]
    return request


# ---- setup_roles ----


def test_setup_roles_creates_three_groups(roles: None) -> None:
    """Команда создаёт ровно три роли проекта."""
    assert set(Group.objects.values_list("name", flat=True)) >= set(ALL_ROLES)


def test_setup_roles_idempotent(roles: None) -> None:
    """Повторный запуск не плодит дубликаты групп."""
    call_command("setup_roles")
    assert Group.objects.filter(name__in=ALL_ROLES).count() == 3


def test_admin_group_has_more_perms_than_viewer(roles: None) -> None:
    """У admin прав строго больше, чем у viewer (полный набор core против личного)."""
    viewer = Group.objects.get(name=ROLE_VIEWER)
    admin = Group.objects.get(name=ROLE_ADMIN)
    assert admin.permissions.count() > viewer.permissions.count()


def test_viewer_perms_are_personal_only(roles: None) -> None:
    """viewer управляет своими видами/экспортом/обратной связью, но не видит аудит."""
    codenames = set(
        Group.objects.get(name=ROLE_VIEWER).permissions.values_list("codename", flat=True)
    )
    assert {"add_savedview", "view_savedview", "add_exportjob", "add_feedbackmessage"} <= codenames
    assert "view_auditlog" not in codenames


def test_admin_can_view_audit(roles: None) -> None:
    """admin располагает правом просмотра журнала аудита."""
    codenames = set(
        Group.objects.get(name=ROLE_ADMIN).permissions.values_list("codename", flat=True)
    )
    assert "view_auditlog" in codenames


# ---- иерархия ролей ----


def test_effective_roles_hierarchy(roles: None) -> None:
    """analyst включает viewer; admin включает все роли."""
    assert effective_roles(_user_in(ROLE_VIEWER)) == {ROLE_VIEWER}
    assert effective_roles(_user_in(ROLE_ANALYST)) == {ROLE_VIEWER, ROLE_ANALYST}
    assert effective_roles(_user_in(ROLE_ADMIN)) == set(ALL_ROLES)


def test_anonymous_has_no_roles() -> None:
    """У анонимного пользователя ролей нет."""
    assert effective_roles(AnonymousUser()) == set()
    assert user_in_role(AnonymousUser(), ROLE_VIEWER) is False


def test_superuser_has_all_roles() -> None:
    """Суперпользователь проходит любую проверку роли (без явного членства в группах)."""
    su = User.objects.create_superuser("root", "root@example.com", "pw-12345")
    assert effective_roles(su) == set(ALL_ROLES)
    assert user_in_role(su, ROLE_ADMIN) is True


def test_analyst_includes_viewer_but_not_admin(roles: None) -> None:
    """analyst проходит как viewer и analyst, но не как admin."""
    analyst = _user_in(ROLE_ANALYST)
    assert user_in_role(analyst, ROLE_VIEWER) is True
    assert user_in_role(analyst, ROLE_ANALYST) is True
    assert user_in_role(analyst, ROLE_ADMIN) is False


# ---- DRF-классы доступа ----


def test_drf_permission_classes(roles: None) -> None:
    """IsViewer/IsAnalyst/IsAppAdmin учитывают иерархию и отклоняют анонима."""
    viewer = _user_in(ROLE_VIEWER)
    analyst = _user_in(ROLE_ANALYST)
    admin = _user_in(ROLE_ADMIN)

    assert IsViewer().has_permission(_drf_request(viewer), None) is True
    assert IsAnalyst().has_permission(_drf_request(viewer), None) is False
    assert IsAnalyst().has_permission(_drf_request(analyst), None) is True
    assert IsAppAdmin().has_permission(_drf_request(analyst), None) is False
    assert IsAppAdmin().has_permission(_drf_request(admin), None) is True
    assert IsViewer().has_permission(_drf_request(AnonymousUser()), None) is False


# ---- декоратор страниц ----


def test_role_required_redirects_anonymous() -> None:
    """Аноним перенаправляется на страницу входа (302 → LOGIN_URL)."""

    @role_required(ROLE_ANALYST)
    def view(request: HttpRequest) -> HttpResponse:
        return HttpResponse("ok")

    request = RequestFactory().get("/secret/")
    request.user = AnonymousUser()  # type: ignore[attr-defined]
    response = view(request)
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_role_required_forbids_wrong_role(roles: None) -> None:
    """Аутентифицированный без нужной роли получает 403 (PermissionDenied)."""

    @role_required(ROLE_ADMIN)
    def view(request: HttpRequest) -> HttpResponse:
        return HttpResponse("ok")

    request = RequestFactory().get("/secret/")
    request.user = _user_in(ROLE_VIEWER)  # type: ignore[attr-defined]
    with pytest.raises(PermissionDenied):
        view(request)


def test_role_required_allows_sufficient_role(roles: None) -> None:
    """Достаточная роль пропускается (200)."""

    @role_required(ROLE_ANALYST)
    def view(request: HttpRequest) -> HttpResponse:
        return HttpResponse("ok")

    request = RequestFactory().get("/secret/")
    request.user = _user_in(ROLE_ANALYST)  # type: ignore[attr-defined]
    response = view(request)
    assert response.status_code == 200
