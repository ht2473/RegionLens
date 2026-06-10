"""Тесты личного кабинета (Ф10·5): доступ только после входа, рендер страниц, владелец-изоляция.

Проверяем: все страницы кабинета требуют входа; у вошедшего открываются (200); правка профиля
сохраняет организацию и e-mail; CRUD сохранённых видов (создание/список/открытие/удаление);
нельзя трогать чужие виды (404); история экспортов показывает только свои; смена пароля.
"""

from __future__ import annotations

import pytest
from core.models import ExportJob, SavedView, UserProfile
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

_PW = "Sl0transit-9"
_CABINET_PAGES = [
    "account",
    "account_profile",
    "account_views",
    "account_exports",
    "account_password",
]


@pytest.fixture
def alice() -> User:
    return User.objects.create_user("alice", password=_PW)


@pytest.fixture
def client_alice(alice: User) -> Client:
    client = Client()
    client.force_login(alice)
    return client


@pytest.mark.parametrize("name", _CABINET_PAGES)
def test_cabinet_requires_login(client: Client, name: str) -> None:
    """Аноним на любой странице кабинета перенаправляется на вход."""
    resp = client.get(reverse(name))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.parametrize("name", _CABINET_PAGES)
def test_cabinet_pages_render(client_alice: Client, name: str) -> None:
    """У вошедшего каждая страница кабинета открывается (200)."""
    assert client_alice.get(reverse(name)).status_code == 200


def test_profile_edit_updates(client_alice: Client, alice: User) -> None:
    """Правка профиля сохраняет организацию (UserProfile) и e-mail (User)."""
    resp = client_alice.post(
        reverse("account_profile"),
        {"organization": "РЭУ", "role_note": "аналитик", "email": "alice@example.com"},
    )
    assert resp.status_code == 200
    alice.refresh_from_db()
    assert alice.email == "alice@example.com"
    assert UserProfile.objects.get(user=alice).organization == "РЭУ"


def test_saved_view_create_and_list(client_alice: Client, alice: User) -> None:
    """Создание вида сохраняет только конфиг и показывает его в списке."""
    resp = client_alice.post(
        reverse("account_views"),
        {
            "name": "Москва 2024",
            "year": "2024",
            "measure": "index",
            "scheme": "equal",
            "okato": "45000000",
        },
    )
    assert resp.status_code == 302
    sv = SavedView.objects.get(user=alice, name="Москва 2024")
    assert sv.config == {"year": 2024, "measure": "index", "scheme": "equal", "okato": "45000000"}
    assert "Москва 2024" in client_alice.get(reverse("account_views")).content.decode()


def test_saved_view_open_region(client_alice: Client, alice: User) -> None:
    """Вид с ОКАТО открывается на странице региона с годом из конфига."""
    sv = SavedView.objects.create(user=alice, name="r", config={"year": 2020, "okato": "45000000"})
    resp = client_alice.get(reverse("account_view_open", args=[sv.pk]))
    assert resp.status_code == 302
    assert reverse("region-dashboard-page", args=["45000000"]) in resp["Location"]
    assert "year=2020" in resp["Location"]


def test_saved_view_open_map(client_alice: Client, alice: User) -> None:
    """Вид без региона открывается на карте с годом и мерой из конфига."""
    sv = SavedView.objects.create(user=alice, name="m", config={"year": 2018, "measure": "cluster"})
    resp = client_alice.get(reverse("account_view_open", args=[sv.pk]))
    assert resp.status_code == 302
    assert reverse("map") in resp["Location"]
    assert "year=2018" in resp["Location"]


def test_saved_view_delete(client_alice: Client, alice: User) -> None:
    """Удаление своего вида (POST) убирает его из БД."""
    sv = SavedView.objects.create(user=alice, name="d", config={})
    resp = client_alice.post(reverse("account_view_delete", args=[sv.pk]))
    assert resp.status_code == 302
    assert not SavedView.objects.filter(pk=sv.pk).exists()


def test_cannot_touch_other_users_view(client_alice: Client) -> None:
    """Чужой сохранённый вид недоступен ни на открытие, ни на удаление (404)."""
    bob = User.objects.create_user("bob", password=_PW)
    sv = SavedView.objects.create(user=bob, name="bobview", config={})
    assert client_alice.get(reverse("account_view_open", args=[sv.pk])).status_code == 404
    assert client_alice.post(reverse("account_view_delete", args=[sv.pk])).status_code == 404
    assert SavedView.objects.filter(pk=sv.pk).exists()


def test_export_history_isolated(client_alice: Client, alice: User) -> None:
    """История экспортов показывает только задания текущего пользователя."""
    bob = User.objects.create_user("bob2", password=_PW)
    ExportJob.objects.create(user=alice, okato="45000000", fmt=ExportJob.Format.XLSX)
    ExportJob.objects.create(user=bob, okato="01000000", fmt=ExportJob.Format.DOCX)
    html = client_alice.get(reverse("account_exports")).content.decode()
    assert "45000000" in html
    assert "01000000" not in html


def test_password_change_flow(client: Client) -> None:
    """Смена пароля принимает старый/новый и редиректит на страницу подтверждения."""
    u = User.objects.create_user("changer", password=_PW)
    client.force_login(u)
    resp = client.post(
        reverse("account_password"),
        {"old_password": _PW, "new_password1": "N3w-transit-pw", "new_password2": "N3w-transit-pw"},
    )
    assert resp.status_code == 302
    assert reverse("account_password_done") in resp["Location"]
