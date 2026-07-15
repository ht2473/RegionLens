"""Представления ядра: серверный рендер публичных страниц + healthcheck.

Контентные страницы (главная, методология, данные, справка) самодостаточны; интерактивные
(карта, рейтинг, типология, сравнение, регионы) — оболочки, наполняемые JS на данных API
в модулях страниц. Каждой странице передаётся active (подсветка меню) и breadcrumbs.
"""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext

from . import queries, reports
from .audit import record
from .forms import RegistrationForm
from .models import ExportJob, Favorite, FeedbackMessage, SavedView, UserProfile
from .permissions import ROLE_VIEWER


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
    crumbs: list[dict[str, str]] = [{"title": gettext("Главная"), "url": reverse("home")}]
    if active != "home":
        crumbs.append({"title": title})
    context: dict[str, object] = {"active": active, "breadcrumbs": crumbs}
    if extra:
        context.update(extra)
    return render(request, template, context)


def home(request: HttpRequest) -> HttpResponse:
    """Главная страница (лендинг)."""
    return _page(
        request,
        "pages/home.html",
        active="home",
        title=gettext("Главная"),
        extra={"region_count": queries.region_count()},
    )


def map_page(request: HttpRequest) -> HttpResponse:
    """Карта регионов (оболочка под MapLibre)."""
    return _page(request, "pages/map.html", active="map", title=gettext("Карта"))


def explore_page(request: HttpRequest) -> HttpResponse:
    """Обзор показателей: любой показатель каталога по регионам за выбранный год (explore)."""
    favorite_metric_ids = []
    if request.user.is_authenticated:
        favorite_metric_ids = list(
            Favorite.objects.filter(user=request.user, kind=Favorite.Kind.METRIC).values_list(
                "ref", flat=True
            )
        )
    return _page(
        request,
        "pages/explore.html",
        active="explore",
        title=gettext("Показатели"),
        extra={"favorite_metric_ids": favorite_metric_ids},
    )


def index_lab_page(request: HttpRequest) -> HttpResponse:
    """Лаборатория индекса: согласованность схем весов и расхождение рейтингов (прозрачность)."""
    return _page(
        request, "pages/index_lab.html", active="index_lab", title=gettext("Лаборатория индекса")
    )


def index_builder_page(request: HttpRequest) -> HttpResponse:
    """Конструктор индекса: рейтинг по пользовательским весам доменов (аналитический инструмент)."""
    return _page(
        request,
        "pages/index_builder.html",
        active="index_builder",
        title=gettext("Конструктор индекса"),
    )


def scenario_page(request: HttpRequest) -> HttpResponse:
    """Сценарный анализ: what-if по перцентилям доменов и изменение места региона."""
    return _page(
        request,
        "pages/scenario.html",
        active="scenario",
        title=gettext("Сценарии"),
    )


def convergence_page(request: HttpRequest) -> HttpResponse:
    """Конвергенция регионов: σ-сходимость индекса и динамика неравенства во времени."""
    return _page(
        request, "pages/convergence.html", active="convergence", title=gettext("Конвергенция")
    )


def public_saved_view(request: HttpRequest, token: str) -> HttpResponse:
    """Публичная ссылка на сохранённый вид (без входа): редирект на восстановленный экран.

    Резолвится в deep-link уже публичных страниц (карта/регион), поэтому ничего приватного
    не раскрывается — это read-only вход в общедоступную аналитику. Токен непустой по маршруту;
    несуществующий или отозванный токен → 404.
    """
    if not token:
        raise Http404
    view = get_object_or_404(SavedView, share_token=token)
    return redirect(view.target_url())


def anomalies_page(request: HttpRequest) -> HttpResponse:
    """Аномалии и структурные сдвиги — модуль «Аналитика» (вход для авторизованных)."""
    return _page(request, "pages/anomalies.html", active="anomalies", title=gettext("Аномалии"))


def correlations_page(request: HttpRequest) -> HttpResponse:
    """Корреляции метрик — модуль «Аналитика» (вход для авторизованных)."""
    return _page(
        request, "pages/correlations.html", active="correlations", title=gettext("Корреляции")
    )


def rankings(request: HttpRequest) -> HttpResponse:
    """Рейтинг регионов по индексу."""
    return _page(
        request,
        "pages/rankings.html",
        active="rankings",
        title=gettext("Рейтинг"),
        extra={"rankings_tab": "ranking"},
    )


def rank_stability_page(request: HttpRequest) -> HttpResponse:
    """Стабильность рейтинга: волатильность ранга регионов — вкладка раздела «Рейтинг»."""
    return _page(
        request,
        "pages/rank_stability.html",
        active="rankings",
        title=gettext("Стабильность рейтинга"),
        extra={"rankings_tab": "stability"},
    )


def typology(request: HttpRequest) -> HttpResponse:
    """Обзор типологии регионов — модуль «Аналитика» (вход для авторизованных)."""
    return _page(request, "pages/typology.html", active="typology", title=gettext("Типология"))


def compare(request: HttpRequest) -> HttpResponse:
    """Сравнение регионов (gap-анализ) — модуль «Аналитика» (вход для авторизованных)."""
    return _page(request, "pages/compare.html", active="compare", title=gettext("Сравнение"))


def regions(request: HttpRequest) -> HttpResponse:
    """Каталог регионов и переход к дашборду."""
    return _page(
        request,
        "pages/regions.html",
        active="regions",
        title=gettext("Регионы"),
        extra={"region_count": queries.region_count()},
    )


def region_dashboard_page(request: HttpRequest, okato: str) -> HttpResponse:
    """Дашборд региона: оболочка; данные (индекс/B4/тип/SHAP/ранг/траектория) тянет region.js."""
    crumbs = [
        {"title": gettext("Главная"), "url": reverse("home")},
        {"title": gettext("Регионы"), "url": reverse("regions")},
        {"title": gettext("Регион")},
    ]
    is_favorited = (
        request.user.is_authenticated
        and Favorite.objects.filter(
            user=request.user, kind=Favorite.Kind.REGION, ref=okato
        ).exists()
    )
    region_label = queries.region_name_ru(okato)
    if request.user.is_authenticated:
        # Запоминаем последний открытый регион для быстрого возврата из обзора кабинета.
        UserProfile.objects.filter(user=request.user).update(last_region_okato=okato)
    return render(
        request,
        "pages/region.html",
        {
            "active": "regions",
            "breadcrumbs": crumbs,
            "okato": okato,
            "export_year": request.GET.get("year", "2024"),
            "is_favorited": is_favorited,
            "region_label": region_label,
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
        title=gettext("Методология"),
        extra={"profile": queries.data_profile()},
    )


def data_page(request: HttpRequest) -> HttpResponse:
    """Источник и охват данных (с реальными числами из хранилища, если оно собрано)."""
    return _page(
        request,
        "pages/data.html",
        active="data",
        title=gettext("Данные"),
        extra={"profile": queries.data_profile(), "data_tab": "source"},
    )


def data_quality_page(request: HttpRequest) -> HttpResponse:
    """Качество данных: полнота/импутации сетки — вкладка «Данные» (оболочка под JS)."""
    return _page(
        request,
        "pages/data_quality.html",
        active="data",
        title=gettext("Качество данных"),
        extra={"data_tab": "quality"},
    )


def dispersion_page(request: HttpRequest) -> HttpResponse:
    """Неравенство регионов: разброс показателей по регионам (оболочка под JS)."""
    return _page(
        request,
        "pages/dispersion.html",
        active="dispersion",
        title=gettext("Неравенство регионов"),
    )


def help_page(request: HttpRequest) -> HttpResponse:
    """Справка по платформе (с данными об авторе)."""
    return _page(request, "pages/help.html", active="help", title=gettext("Справка"))


def _model_cards() -> list[dict[str, object]]:
    """Карточки обученных моделей для витрины (best-effort чтение из каталога моделей)."""
    labels = {
        "typology_classifier": gettext("Классификатор типологии"),
        "anomaly_detector": gettext("Детектор аномалий"),
    }
    metric_labels = {
        "cv_accuracy": gettext("Точность (кросс-валидация)"),
        "anomaly_share": gettext("Доля аномалий"),
    }
    try:
        from pipeline.models_io import list_model_cards

        cards = list_model_cards(models_dir=Path(settings.MODELS_DIR))
    except Exception:  # noqa: BLE001 — витрина не должна падать из-за отсутствия/ошибки моделей
        return []

    result: list[dict[str, object]] = []
    for card in cards:
        metrics = [
            {
                "label": metric_labels.get(key, key),
                "value": f"{value * 100:.1f}%" if 0 <= value <= 1 else f"{value:.3f}",
            }
            for key, value in card.metrics.items()
        ]
        result.append(
            {
                "name": card.name,
                "label": labels.get(card.name, card.name),
                "alias": card.alias,
                "estimator": card.estimator,
                "created": card.created,
                "sklearn_version": card.sklearn_version,
                "n_samples": card.n_samples,
                "n_features": len(card.feature_names),
                "params": card.params,
                "metrics": metrics,
            }
        )
    return result


def models_page(request: HttpRequest) -> HttpResponse:
    """Витрина ML-моделей: карточки управляемых моделей (метрики, версия, дата обучения)."""
    return _page(
        request,
        "pages/models.html",
        active="models",
        title=gettext("Модели"),
        extra={"model_cards": _model_cards()},
    )


def feedback(request: HttpRequest) -> HttpResponse:
    """Обратная связь: приём и сохранение сообщения (анонимного или от пользователя) + аудит."""
    crumbs = [
        {"title": gettext("Главная"), "url": reverse("home")},
        {"title": gettext("Обратная связь")},
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
        {"title": gettext("Главная"), "url": reverse("home")},
        {"title": gettext("Регистрация")},
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
