"""Тесты публичных страниц (Ф7, модуль 1): доступность, хлебные крошки, меню, подвал.

Страницы — серверный рендер без обращения к ORM/Postgres, поэтому маркер django_db не нужен.
"""

from __future__ import annotations

import pytest
from django.test import Client

PAGES = [
    "/",
    "/map/",
    "/rankings/",
    "/typology/",
    "/compare/",
    "/regions/",
    "/methodology/",
    "/data/",
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


def test_feedback_post_acknowledges(client: Client) -> None:
    """POST с текстом подтверждается (сохранение в БД — в Ф10)."""
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
