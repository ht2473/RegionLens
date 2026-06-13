"""Представления ядра (Ф7): серверный рендер публичных страниц + healthcheck.

Контентные страницы (главная, методология, данные, справка) самодостаточны; интерактивные
(карта, рейтинг, типология, сравнение, регионы) — оболочки, наполняемые JS на данных API
в следующих модулях Ф7. Каждой странице передаётся active (подсветка меню) и breadcrumbs.
"""

import re

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from . import queries, reports
from .audit import record
from .forms import RegistrationForm
from .models import ExportJob, FeedbackMessage
from .permissions import ROLE_ANALYST, ROLE_VIEWER, role_required


def healthz(request: HttpRequest) -> JsonResponse:
    """Проверка живости: приложение поднялось и отвечает."""
    return JsonResponse({"status": "ok", "service": "regionlens"})


def _page(
    request: HttpRequest,
    template: str,
    *,
    active: str,
    title: str,
    extra: dict[str, object] | None = None,
) -> HttpResponse:
    """Отрисовать страницу с подсветкой меню и хлебными крошками (Главная → title).

    extra — необязательный дополнительный контекст шаблона (например, сводка по данным
    для страниц «Данные»/«Методология»).
    """
    crumbs: list[dict[str, str]] = [{"title": "Главная", "url": reverse("home")}]
    if active != "home":
        crumbs.append({"title": title})
    context: dict[str, object] = {"active": active, "breadcrumbs": crumbs}
    if extra:
        context.update(extra)
    return render(request, template, context)


def home(request: HttpRequest) -> HttpResponse:
    """Главная страница (лендинг)."""
    return _page(request, "pages/home.html", active="home", title="Главная")


def map_page(request: HttpRequest) -> HttpResponse:
    """Карта регионов (оболочка под MapLibre)."""
    return _page(request, "pages/map.html", active="map", title="Карта")


@role_required(ROLE_ANALYST)
def anomalies_page(request: HttpRequest) -> HttpResponse:
    """Аномалии и структурные сдвиги (Ф9) — расширенная аналитика, только роль analyst."""
    return _page(request, "pages/anomalies.html", active="anomalies", title="Аномалии")


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
        {
            "active": "regions",
            "breadcrumbs": crumbs,
            "okato": okato,
            "export_year": request.GET.get("year", "2024"),
        },
    )


# ОКАТО региона — только цифры (длина 2–12). Строгий allowlist на границе входа гарантирует,
# что в имя файла экспорта (region_<okato>_<year>.<fmt>) не попадут разделители пути или `..`,
# — это закрывает path traversal при записи в MEDIA_ROOT/exports/.
_OKATO_RE = re.compile(r"^\d{2,12}$")


def _validated_okato(okato: str) -> str:
    """Проверить код ОКАТО по строгому шаблону; иначе 404 (защита экспорта от traversal)."""
    if not _OKATO_RE.match(okato):
        raise Http404("Некорректный код региона.")
    return okato


@login_required
def export_region(request: HttpRequest, okato: str) -> HttpResponse:
    """Сформировать отчёт региона (xlsx/docx), записать ExportJob и отдать файл на скачивание.

    Доступ только для вошедших; задание привязывается к текущему пользователю и попадает в
    «Историю экспортов» кабинета. Год берётся из ?year= (по умолчанию 2024). `okato` проходит
    строгую валидацию — пользовательский ввод не достигает файловой системы в сыром виде.
    """
    fmt = request.GET.get("format", "xlsx")
    if fmt not in ("xlsx", "docx"):
        raise Http404("Неизвестный формат экспорта.")
    okato = _validated_okato(okato)
    try:
        year = int(request.GET.get("year") or 2024)
    except (TypeError, ValueError):
        raise Http404("Некорректный год.") from None

    data = queries.region_dashboard(okato, year)
    if data is None:
        raise Http404("Нет данных по региону за выбранный год.")

    content = reports.region_xlsx(data) if fmt == "xlsx" else reports.region_docx(data)
    job = ExportJob(user=request.user, okato=okato, fmt=fmt, status=ExportJob.Status.DONE)
    filename = f"region_{okato}_{year}.{fmt}"
    job.file.save(filename, ContentFile(content))  # save=True: сохраняет и сам ExportJob
    record(request.user, f"export:{fmt} okato={okato} year={year}")
    return FileResponse(job.file.open("rb"), as_attachment=True, filename=filename)


def methodology(request: HttpRequest) -> HttpResponse:
    """Методология расчётов (с реальными числами из хранилища, если оно собрано)."""
    return _page(
        request,
        "pages/methodology.html",
        active="methodology",
        title="Методология",
        extra={"profile": queries.data_profile()},
    )


def data_page(request: HttpRequest) -> HttpResponse:
    """Источник и охват данных (с реальными числами из хранилища, если оно собрано)."""
    return _page(
        request,
        "pages/data.html",
        active="data",
        title="Данные",
        extra={"profile": queries.data_profile()},
    )


def help_page(request: HttpRequest) -> HttpResponse:
    """Справка по платформе (с данными об авторе)."""
    return _page(request, "pages/help.html", active="help", title="Справка")


def feedback(request: HttpRequest) -> HttpResponse:
    """Обратная связь: приём и сохранение сообщения (анонимного или от пользователя) + аудит."""
    crumbs = [
        {"title": "Главная", "url": reverse("home")},
        {"title": "Обратная связь"},
    ]
    sent = False
    if request.method == "POST":
        text = request.POST.get("text", "").strip()
        if text:
            name = request.POST.get("name", "").strip()
            user = request.user if request.user.is_authenticated else None
            stored = f"{name}: {text}" if name and user is None else text
            FeedbackMessage.objects.create(user=user, text=stored[:4000])
            record(user, "feedback:submit")
            sent = True
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
            record(user, f"user:register {user.username}")
            login(request, user)
            return redirect("home")
    else:
        form = RegistrationForm()
    return render(
        request,
        "registration/register.html",
        {"active": "register", "breadcrumbs": crumbs, "form": form},
    )
