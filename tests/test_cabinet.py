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
    "account_favorites",
    "account_activity",
    "account_comparisons",
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


# --- Публичный шаринг сохранённых видов (Фаза 3) -------------------------------------


def test_saved_view_share_toggle(client_alice: Client, alice: User) -> None:
    """Кнопка доступа включает публичную ссылку (токен), повторное нажатие — отзывает."""
    sv = SavedView.objects.create(user=alice, name="s", config={"year": 2020})
    client_alice.post(reverse("account_view_share", args=[sv.pk]))
    sv.refresh_from_db()
    assert sv.is_shared and sv.share_token
    client_alice.post(reverse("account_view_share", args=[sv.pk]))
    sv.refresh_from_db()
    assert not sv.is_shared and sv.share_token == ""


def test_saved_view_share_requires_login(client: Client, alice: User) -> None:
    """Аноним не может менять доступ к виду — редирект на вход."""
    sv = SavedView.objects.create(user=alice, name="s", config={})
    resp = client.post(reverse("account_view_share", args=[sv.pk]))
    assert resp.status_code == 302 and "/accounts/login/" in resp["Location"]


def test_cannot_share_other_users_view(client_alice: Client) -> None:
    """Нельзя открыть доступ к чужому виду (404), вид остаётся закрытым."""
    bob = User.objects.create_user("bob", password=_PW)
    sv = SavedView.objects.create(user=bob, name="bobview", config={})
    assert client_alice.post(reverse("account_view_share", args=[sv.pk])).status_code == 404
    sv.refresh_from_db()
    assert not sv.is_shared


def test_public_view_redirects_to_region(client: Client, alice: User) -> None:
    """Публичная ссылка (регион) → 302 на дашборд региона с годом, без входа."""
    sv = SavedView.objects.create(user=alice, name="r", config={"year": 2020, "okato": "45000000"})
    sv.enable_sharing()
    resp = client.get(reverse("public_saved_view", args=[sv.share_token]))
    assert resp.status_code == 302
    assert resp["Location"] == "/regions/45000000/?year=2020"


def test_public_view_redirects_to_map(client: Client, alice: User) -> None:
    """Публичная ссылка (карта) → 302 на карту с годом и мерой."""
    sv = SavedView.objects.create(user=alice, name="m", config={"year": 2018, "measure": "index"})
    sv.enable_sharing()
    resp = client.get(reverse("public_saved_view", args=[sv.share_token]))
    assert resp["Location"] == "/map/?year=2018&measure=index"


def test_public_view_unknown_token_404(client: Client) -> None:
    """Несуществующий токен публичной ссылки → 404."""
    assert client.get("/views/nope-not-a-real-token/").status_code == 404


def test_public_view_revoked_token_404(client: Client, alice: User) -> None:
    """После отзыва доступа прежний токен больше не открывается (404)."""
    sv = SavedView.objects.create(user=alice, name="x", config={"year": 2021})
    sv.enable_sharing()
    token = sv.share_token
    sv.disable_sharing()
    assert client.get(reverse("public_saved_view", args=[token])).status_code == 404


def test_enable_sharing_is_idempotent(alice: User) -> None:
    """enable_sharing генерирует токен один раз; повторный вызов его не меняет."""
    sv = SavedView.objects.create(user=alice, name="i", config={})
    sv.enable_sharing()
    first = sv.share_token
    sv.enable_sharing()
    assert sv.share_token == first and len(first) >= 32


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


# ── Избранное (Ф10·5): переключение, изоляция владельца, требование входа ───────
def test_favorite_toggle_add_and_remove(client_alice: Client, alice: User) -> None:
    """Первый POST добавляет закладку, повторный — снимает (идемпотентно по kind+ref)."""
    from core.models import Favorite

    url = reverse("favorite_toggle")
    resp = client_alice.post(url, {"kind": "region", "ref": "45000000", "label": "Москва"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["favorited"] is True and body["count"] == 1
    assert Favorite.objects.filter(user=alice, kind="region", ref="45000000").exists()

    resp = client_alice.post(url, {"kind": "region", "ref": "45000000", "label": "Москва"})
    assert resp.json()["favorited"] is False
    assert not Favorite.objects.filter(user=alice, kind="region", ref="45000000").exists()


def test_favorite_toggle_rejects_bad_kind(client_alice: Client) -> None:
    """Неизвестный тип закладки отклоняется (400)."""
    resp = client_alice.post(reverse("favorite_toggle"), {"kind": "planet", "ref": "1"})
    assert resp.status_code == 400


def test_favorite_toggle_requires_login(client: Client) -> None:
    """Аноним не может переключать избранное — редирект на вход."""
    resp = client.post(reverse("favorite_toggle"), {"kind": "region", "ref": "45000000"})
    assert resp.status_code == 302 and "/accounts/login/" in resp["Location"]


def test_favorites_list_shows_only_own(client_alice: Client, alice: User) -> None:
    """На странице «Избранное» видны только свои закладки (изоляция владельца)."""
    from core.models import Favorite

    Favorite.objects.create(user=alice, kind="metric", ref="123", label="Некий показатель")
    other = User.objects.create_user("mallory", password=_PW)
    Favorite.objects.create(user=other, kind="metric", ref="999", label="Чужой показатель")
    html = client_alice.get(reverse("account_favorites")).content.decode()
    assert "Некий показатель" in html
    assert "Чужой показатель" not in html


def test_activity_feed_lists_user_actions(client_alice: Client, alice: User) -> None:
    """Лента активности показывает описанные действия из журнала аудита пользователя."""
    from core.audit import record

    record(alice, "saved_view:create Мой вид")
    html = client_alice.get(reverse("account_activity")).content.decode()
    assert "Мой вид" in html


def test_overview_shows_favorite_count(client_alice: Client, alice: User) -> None:
    """Обзор кабинета отражает число закладок в персональной сводке."""
    from core.models import Favorite

    Favorite.objects.create(user=alice, kind="region", ref="45000000", label="Москва")
    html = client_alice.get(reverse("account")).content.decode()
    assert "В избранном" in html


# ── Наборы сравнения (Ф10·5): сохранение, валидация, изоляция, открытие, удаление ──
def test_comparison_save_creates_set(client_alice: Client, alice: User) -> None:
    """POST со страницы сравнения создаёт набор из 2–3 регионов и года."""
    from core.models import ComparisonSet

    resp = client_alice.post(
        reverse("comparison_save"),
        {"name": "ЦФО тройка", "okato": ["45000000", "46000000", "17000000"], "year": "2023"},
    )
    assert resp.status_code == 200 and resp.json()["ok"] is True
    cs = ComparisonSet.objects.get(user=alice, name="ЦФО тройка")
    assert cs.okatos == ["45000000", "46000000", "17000000"] and cs.year == 2023


def test_comparison_save_rejects_wrong_count(client_alice: Client) -> None:
    """Набор из одного региона отклоняется (нужно 2–3)."""
    resp = client_alice.post(
        reverse("comparison_save"), {"name": "Один", "okato": ["45000000"], "year": "2024"}
    )
    assert resp.status_code == 400


def test_comparison_save_rejects_bad_okato(client_alice: Client) -> None:
    """Нецифровой код региона отбраковывается — остаётся меньше двух → 400."""
    resp = client_alice.post(
        reverse("comparison_save"),
        {"name": "Кривой", "okato": ["45000000", "../etc"], "year": "2024"},
    )
    assert resp.status_code == 400


def test_comparison_open_redirects_to_compare(client_alice: Client, alice: User) -> None:
    """Открытие набора ведёт на страницу сравнения с предвыбранными регионами и годом."""
    from core.models import ComparisonSet

    cs = ComparisonSet.objects.create(
        user=alice, name="Пара", okatos=["45000000", "78000000"], year=2022
    )
    resp = client_alice.get(reverse("comparison_open", args=[cs.pk]))
    assert resp.status_code == 302
    loc = resp["Location"]
    assert "okato=45000000" in loc and "okato=78000000" in loc and "year=2022" in loc


def test_comparison_delete_and_owner_isolation(client_alice: Client, alice: User) -> None:
    """Удалять можно только свой набор; чужой недоступен (404)."""
    from core.models import ComparisonSet

    mine = ComparisonSet.objects.create(user=alice, name="Моё", okatos=["45000000", "78000000"])
    other = User.objects.create_user("bob", password=_PW)
    theirs = ComparisonSet.objects.create(user=other, name="Чужое", okatos=["45000000", "78000000"])
    assert client_alice.post(reverse("comparison_delete", args=[mine.pk])).status_code == 302
    assert not ComparisonSet.objects.filter(pk=mine.pk).exists()
    assert client_alice.post(reverse("comparison_delete", args=[theirs.pk])).status_code == 404


def test_comparison_save_requires_login(client: Client) -> None:
    """Аноним не может сохранять наборы — редирект на вход."""
    resp = client.post(reverse("comparison_save"), {"name": "x", "okato": ["45000000", "78000000"]})
    assert resp.status_code == 302 and "/accounts/login/" in resp["Location"]


# ── Экспорт-центр (Ф10·5): быстрый экспорт + ярлыки избранного + история ────────
def test_export_center_shows_quick_export(client_alice: Client) -> None:
    """Экспорт-центр показывает форму быстрого экспорта."""
    html = client_alice.get(reverse("account_exports")).content.decode()
    assert "qe-region" in html and "qe-go" in html


def test_export_center_lists_favorite_region_shortcuts(client_alice: Client, alice: User) -> None:
    """Избранные регионы появляются как ярлыки быстрого экспорта (XLSX/DOCX)."""
    from core.models import Favorite

    Favorite.objects.create(user=alice, kind="region", ref="45000000", label="Москва")
    html = client_alice.get(reverse("account_exports")).content.decode()
    assert "/regions/45000000/export/?format=xlsx" in html
    assert "/regions/45000000/export/?format=docx" in html
