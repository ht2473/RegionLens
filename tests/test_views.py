"""Тесты публичных страниц (Ф7, модуль 1): доступность, хлебные крошки, меню, подвал.

Страницы — серверный рендер без обращения к ORM/Postgres, поэтому маркер django_db в общем
не нужен (исключение — POST обратной связи, который с Ф10·7 сохраняет сообщение в БД).
"""

from __future__ import annotations

import pytest
from django.test import Client

PAGES = [
    "/",
    "/map/",
    "/rankings/",
    "/rankings/stability/",
    "/typology/",
    "/compare/",
    "/regions/",
    "/methodology/",
    "/data/",
    "/data/quality/",
    "/dispersion/",
    "/help/",
    "/feedback/",
]

MENU_LABELS = [
    "Главная",
    "Карта",
    "Рейтинг",
    "Типология",
    "Сравнение",
    "Регионы",
    "Методология",
    "Данные",
    "Неравенство",
    "Справка",
    "Обратная связь",
]


@pytest.mark.parametrize("url", PAGES)
def test_page_ok(client: Client, url: str) -> None:
    """Каждая публичная страница отдаётся со статусом 200."""
    assert client.get(url).status_code == 200


@pytest.mark.parametrize("url", PAGES)
def test_page_has_breadcrumbs(client: Client, url: str) -> None:
    """На каждой странице присутствует блок хлебных крошек."""
    assert 'class="crumbs"' in client.get(url).content.decode()


@pytest.mark.parametrize("url", PAGES)
def test_page_has_footer_author(client: Client, url: str) -> None:
    """Подвал с ФИО автора и номером студбилета присутствует везде."""
    html = client.get(url).content.decode()
    assert "Кузьмин Евгений Олегович" in html
    assert "70232275" in html


def test_public_pages_count(client: Client) -> None:
    """Публичных страниц не меньше 10 (требование вуза)."""
    assert len(PAGES) >= 10
    assert all(client.get(url).status_code == 200 for url in PAGES)


def test_nav_has_all_menu_items(client: Client) -> None:
    """Меню содержит все 10 пунктов."""
    html = client.get("/").content.decode()
    for label in MENU_LABELS:
        assert label in html


def test_active_menu_highlight(client: Client) -> None:
    """Текущий раздел подсвечен в меню (класс is-active)."""
    assert "is-active" in client.get("/map/").content.decode()


def test_feedback_get_shows_form(client: Client) -> None:
    """GET обратной связи показывает форму."""
    html = client.get("/feedback/").content.decode()
    assert "<form" in html and 'name="text"' in html


@pytest.mark.django_db
def test_feedback_post_acknowledges(client: Client) -> None:
    """POST с текстом сохраняется в БД (Ф10·7) и подтверждается на странице."""
    html = client.post("/feedback/", {"text": "тест"}).content.decode()
    assert "Сообщение получено" in html


def test_map_page_wiring(client: Client) -> None:
    """Страница карты подключает MapLibre, map.js, ползунок лет и переключатель меры."""
    html = client.get("/map/").content.decode()
    assert "maplibre-gl" in html
    assert "js/map.js" in html
    assert 'id="year-slider"' in html
    assert 'data-measure="cluster"' in html and 'data-measure="index"' in html


def test_regions_list_wiring(client: Client) -> None:
    """Список регионов подключает Alpine-компонент на /api/regions/."""
    html = client.get("/regions/").content.decode()
    assert "regionsList()" in html
    assert "/api/regions/" in html


def test_region_dashboard_page(client: Client) -> None:
    """Дашборд региона: 200, okato в data-атрибуте, Plotly+region.js, ползунок, крошки, подвал."""
    html = client.get("/regions/45000000/").content.decode()
    assert 'data-okato="45000000"' in html
    assert "js/region.js" in html
    assert "plot.ly" in html
    assert 'id="year-slider"' in html
    assert 'class="crumbs"' in html
    assert "Кузьмин Евгений Олегович" in html


def test_region_dashboard_passes_okato(client: Client) -> None:
    """Любой okato из пути пробрасывается в шаблон (валидность проверяет API в JS)."""
    assert client.get("/regions/77000000/").status_code == 200
    assert 'data-okato="77000000"' in client.get("/regions/77000000/").content.decode()


def test_rankings_page_wiring(client: Client) -> None:
    """Рейтинг: rankings.js, контейнер, контролы год/схема."""
    html = client.get("/rankings/").content.decode()
    assert "js/rankings.js" in html
    assert 'id="rankings-root"' in html
    assert 'id="year-slider"' in html and 'id="scheme-select"' in html
    assert 'value="equal"' in html and 'value="pca"' in html and 'value="expert"' in html


def test_compare_page_wiring(client: Client) -> None:
    """Сравнение: compare.js, Plotly, три выбора региона, год, кнопка."""
    html = client.get("/compare/").content.decode()
    assert "js/compare.js" in html
    assert "plot.ly" in html
    assert 'id="cmp-1"' in html and 'id="cmp-2"' in html and 'id="cmp-3"' in html
    assert 'id="cmp-go"' in html and 'id="year-slider"' in html


def test_typology_page_wiring(client: Client) -> None:
    """Обзор типологии: typology.js, Plotly, контейнер, ползунок года."""
    html = client.get("/typology/").content.decode()
    assert "js/typology.js" in html
    assert "plot.ly" in html
    assert 'id="typology-root"' in html
    assert 'id="year-slider"' in html


def test_page_names_resolve_to_pages_not_api() -> None:
    """Имена маршрутов страниц ведут на страницы, а не на /api/ (защита от коллизии имён)."""
    from django.urls import reverse

    assert reverse("typology") == "/typology/"
    assert reverse("compare") == "/compare/"
    assert reverse("regions") == "/regions/"
    assert reverse("api:typology") == "/api/typology/"


def test_menu_links_point_to_pages(client: Client) -> None:
    """Ссылки меню на главной ведут на страницы (не на API-эндпойнты)."""
    html = client.get("/").content.decode()
    assert 'href="/typology/"' in html
    assert 'href="/compare/"' in html
    assert 'href="/regions/"' in html
    assert 'href="/api/' not in html


def _role_client(role: str) -> Client:
    """Client, залогиненный пользователем с заданной ролью (группа создаётся при нужде)."""
    from django.contrib.auth.models import Group, User

    user = User.objects.create_user(username=f"pg_{role}", password="x")
    group, _ = Group.objects.get_or_create(name=role)
    user.groups.add(group)
    client = Client()
    client.force_login(user)
    return client


def test_anomalies_page_redirects_anonymous() -> None:
    """Страница аномалий под ролью analyst: аноним → редирект на вход (302)."""
    resp = Client().get("/anomalies/")
    assert resp.status_code == 302 and "login" in resp.headers["Location"]


@pytest.mark.django_db
def test_anomalies_page_forbidden_for_viewer() -> None:
    """viewer не имеет доступа к расширенной аналитике → 403."""
    assert _role_client("viewer").get("/anomalies/").status_code == 403


@pytest.mark.django_db
def test_anomalies_page_ok_for_analyst() -> None:
    """analyst → 200; страница содержит карту, оба списка и подключает anomalies.js."""
    html = _role_client("analyst").get("/anomalies/").content.decode()
    assert 'id="map"' in html
    assert 'id="breaks-list"' in html and 'id="methodology-list"' in html
    assert "js/anomalies.js" in html


@pytest.mark.django_db
def test_anomalies_menu_item_visible_only_to_analyst() -> None:
    """Пункт меню «Аномалии» виден analyst и скрыт у viewer."""
    assert "Аномалии" in _role_client("analyst").get("/").content.decode()
    assert "Аномалии" not in _role_client("viewer").get("/").content.decode()


def test_dispersion_page_shell(client: Client) -> None:
    """Страница «Неравенство регионов» публична и содержит селектор метрики и корень под JS."""
    html = client.get("/dispersion/").content.decode()
    assert 'id="metric-select"' in html
    assert 'id="dispersion-root"' in html
    assert "js/dispersion.js" in html


def test_dispersion_nav_active(client: Client) -> None:
    """На странице неравенства пункт меню «Неравенство» подсвечен как активный."""
    html = client.get("/dispersion/").content.decode()
    assert "is-active" in html
    assert "Неравенство" in html


def test_rank_stability_page_shell(client: Client) -> None:
    """Вкладка «Стабильность» публична: содержит подвкладки рейтинга, селектор схемы и корень."""
    html = client.get("/rankings/stability/").content.decode()
    assert 'id="scheme-select"' in html
    assert 'id="rank-stability-root"' in html
    assert "js/rank_stability.js" in html
    assert "Стабильность" in html  # подвкладка


def test_rankings_subnav_links_both_tabs(client: Client) -> None:
    """На странице рейтинга есть подвкладки на «Рейтинг» и «Стабильность»."""
    html = client.get("/rankings/").content.decode()
    assert 'class="subnav"' in html
    assert "/rankings/stability/" in html


def test_data_quality_page_shell(client: Client) -> None:
    """Вкладка «Качество данных» публична: содержит подвкладки данных, корень и подключает JS."""
    html = client.get("/data/quality/").content.decode()
    assert 'class="subnav"' in html
    assert 'id="data-quality-root"' in html
    assert "js/data_quality.js" in html
    assert "Качество" in html  # подвкладка


def test_data_subnav_links_both_tabs(client: Client) -> None:
    """На странице «Данные» есть подвкладки на «Источник и охват» и «Качество»."""
    html = client.get("/data/").content.decode()
    assert 'class="subnav"' in html
    assert "/data/quality/" in html


def test_data_quality_nav_active_data(client: Client) -> None:
    """На вкладке качества подсвечен пункт верхнего меню «Данные» (active='data')."""
    html = client.get("/data/quality/").content.decode()
    assert "is-active" in html
    assert "Данные" in html


def test_correlations_page_redirects_anonymous() -> None:
    """Страница корреляций под ролью analyst: аноним → редирект на вход (302)."""
    resp = Client().get("/correlations/")
    assert resp.status_code == 302 and "login" in resp.headers["Location"]


@pytest.mark.django_db
def test_correlations_page_forbidden_for_viewer() -> None:
    """viewer не имеет доступа к корреляциям → 403."""
    assert _role_client("viewer").get("/correlations/").status_code == 403


@pytest.mark.django_db
def test_correlations_page_ok_for_analyst() -> None:
    """analyst → 200; есть плашка про причинность, селектор, корень и подключение JS."""
    html = _role_client("analyst").get("/correlations/").content.decode()
    assert "причинность" in html  # плашка-предупреждение
    assert 'id="metric-select"' in html and 'id="correlations-root"' in html
    assert 'id="year-slider"' in html  # выбор года (Ф15)
    assert "js/correlations.js" in html


@pytest.mark.django_db
def test_correlations_menu_item_visible_only_to_analyst() -> None:
    """Пункт меню «Корреляции» виден analyst и скрыт у viewer."""
    assert "Корреляции" in _role_client("analyst").get("/").content.decode()
    assert "Корреляции" not in _role_client("viewer").get("/").content.decode()
