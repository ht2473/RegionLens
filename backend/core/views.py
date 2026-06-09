"""Представления ядра (Ф7): серверный рендер публичных страниц + healthcheck.

Контентные страницы (главная, методология, данные, справка) самодостаточны; интерактивные
(карта, рейтинг, типология, сравнение, регионы) — оболочки, наполняемые JS на данных API
в следующих модулях Ф7. Каждой странице передаётся active (подсветка меню) и breadcrumbs.
"""

from django.contrib.auth import login
from django.contrib.auth.models import Group
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from .forms import RegistrationForm
from .permissions import ROLE_VIEWER


def healthz(request: HttpRequest) -> JsonResponse:
    """Проверка живости: приложение поднялось и отвечает."""
    return JsonResponse({"status": "ok", "service": "regionlens"})


def _page(request: HttpRequest, template: str, *, active: str, title: str) -> HttpResponse:
    """Отрисовать страницу с подсветкой меню и хлебными крошками (Главная → title)."""
    crumbs: list[dict[str, str]] = [{"title": "Главная", "url": reverse("home")}]
    if active != "home":
        crumbs.append({"title": title})
    return render(
        request,
        template,
        {"active": active, "breadcrumbs": crumbs},
    )


def home(request: HttpRequest) -> HttpResponse:
    """Главная страница (лендинг)."""
    return _page(request, "pages/home.html", active="home", title="Главная")


def map_page(request: HttpRequest) -> HttpResponse:
    """Карта регионов (оболочка под MapLibre)."""
    return _page(request, "pages/map.html", active="map", title="Карта")


def rankings(request: HttpRequest) -> HttpResponse:
    """Рейтинг регионов по индексу."""
    return _page(request, "pages/rankings.html", active="rankings", title="Рейтинг")


def typology(request: HttpRequest) -> HttpResponse:
    """Обзор типологии регионов."""
    return _page(request, "pages/typology.html", active="typology", title="Типология")


def compare(request: HttpRequest) -> HttpResponse:
    """Сравнение регионов (gap-анализ)."""
    return _page(request, "pages/compare.html", active="compare", title="Сравнение")


def regions(request: HttpRequest) -> HttpResponse:
    """Каталог регионов и переход к дашборду."""
    return _page(request, "pages/regions.html", active="regions", title="Регионы")


def region_dashboard_page(request: HttpRequest, okato: str) -> HttpResponse:
    """Дашборд региона: оболочка; данные (индекс/B4/тип/SHAP/ранг/траектория) тянет region.js."""
    crumbs = [
        {"title": "Главная", "url": reverse("home")},
        {"title": "Регионы", "url": reverse("regions")},
        {"title": "Регион"},
    ]
    return render(
        request,
        "pages/region.html",
        {"active": "regions", "breadcrumbs": crumbs, "okato": okato},
    )


def methodology(request: HttpRequest) -> HttpResponse:
    """Методология расчётов."""
    return _page(request, "pages/methodology.html", active="methodology", title="Методология")


def data_page(request: HttpRequest) -> HttpResponse:
    """Источник и охват данных."""
    return _page(request, "pages/data.html", active="data", title="Данные")


def help_page(request: HttpRequest) -> HttpResponse:
    """Справка по платформе (с данными об авторе)."""
    return _page(request, "pages/help.html", active="help", title="Справка")


def feedback(request: HttpRequest) -> HttpResponse:
    """Обратная связь. Приём сообщения; постоянное хранение подключается в Ф10."""
    crumbs = [
        {"title": "Главная", "url": reverse("home")},
        {"title": "Обратная связь"},
    ]
    sent = request.method == "POST" and bool(request.POST.get("text", "").strip())
    return render(
        request,
        "pages/feedback.html",
        {"active": "feedback", "breadcrumbs": crumbs, "sent": sent},
    )


def register(request: HttpRequest) -> HttpResponse:
    """Регистрация: создаёт пользователя, назначает роль viewer и выполняет вход.

    Профиль пользователя создаётся сигналом (см. core/signals.py). Уже вошедший
    пользователь перенаправляется на главную.
    """
    crumbs = [
        {"title": "Главная", "url": reverse("home")},
        {"title": "Регистрация"},
    ]
    if request.user.is_authenticated:
        return redirect("home")
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            group, _ = Group.objects.get_or_create(name=ROLE_VIEWER)
            user.groups.add(group)
            login(request, user)
            return redirect("home")
    else:
        form = RegistrationForm()
    return render(
        request,
        "registration/register.html",
        {"active": "register", "breadcrumbs": crumbs, "form": form},
    )
