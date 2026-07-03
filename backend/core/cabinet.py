"""Личный кабинет: обзор, профиль, сохранённые виды, история экспортов.

Все страницы требуют входа (`login_required`) и показывают данные ТОЛЬКО текущего
пользователя — операционные модели фильтруются по `request.user` (изоляция владельца).
Смена пароля реализована штатными PasswordChange[Done]View в `urls.py`.
"""

from __future__ import annotations

import json
import re

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from .audit import record
from .forms import PreferencesForm, ProfileForm, SavedViewForm
from .models import AuditLog, ComparisonSet, ExportJob, Favorite, SavedView, UserProfile
from .permissions import effective_roles
from .queries import data_freshness, region_names_ru


def _crumbs(tail_title: str) -> list[dict[str, str | None]]:
    """Крошки кабинета: Главная → Личный кабинет → <раздел>."""
    return [
        {"title": gettext("Главная"), "url": reverse("home")},
        {"title": gettext("Личный кабинет"), "url": "/account/"},
        {"title": tail_title, "url": None},
    ]


@login_required
def overview(request: HttpRequest) -> HttpResponse:
    """Обзорная страница кабинета: роль, счётчики видов и экспортов, быстрые ссылки."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    ctx = {
        "active": "account",
        "cabinet_tab": "overview",
        "breadcrumbs": [
            {"title": gettext("Главная"), "url": reverse("home")},
            {"title": gettext("Личный кабинет"), "url": None},
        ],
        "profile": profile,
        "roles": sorted(effective_roles(request.user)),
        "saved_count": SavedView.objects.filter(user=request.user).count(),
        "export_count": ExportJob.objects.filter(user=request.user).count(),
        "favorite_count": Favorite.objects.filter(user=request.user).count(),
        "comparison_count": ComparisonSet.objects.filter(user=request.user).count(),
        "recent_activity": _activity_events(request.user, limit=6),
        "recent_favorites": _localized_favorites(request.user)[:6],
        "continue_links": _continue_links(request.user, profile),
        "freshness": data_freshness(),
    }
    return render(request, "account/overview.html", ctx)


def _continue_links(user: object, profile: UserProfile) -> list[dict[str, object]]:
    """Быстрые ссылки «продолжить с того же места»: последний регион, вид, набор сравнения."""
    links: list[dict[str, object]] = []
    if profile.last_region_okato:
        okato = profile.last_region_okato
        raw = region_names_ru([okato]).get(okato, "")
        label = gettext(raw) if raw else okato
        links.append(
            {
                "kind": gettext("Регион"),
                "label": label,
                "url": reverse("region-dashboard-page", args=[okato]),
            }
        )
    view = SavedView.objects.filter(user=user).first()
    if view is not None:
        links.append({"kind": gettext("Вид"), "label": view.name, "url": view.target_url()})
    cs = ComparisonSet.objects.filter(user=user).first()
    if cs is not None:
        links.append({"kind": gettext("Сравнение"), "label": cs.name, "url": cs.target_url()})
    return links


@login_required
def profile_edit(request: HttpRequest) -> HttpResponse:
    """Просмотр и редактирование профиля (организация, заметка о роли, e-mail)."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    saved = False
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            request.user.email = form.cleaned_data["email"]
            request.user.save(update_fields=["email"])
            saved = True
    else:
        form = ProfileForm(instance=profile, initial={"email": request.user.email})
    ctx = {
        "active": "account",
        "cabinet_tab": "profile",
        "breadcrumbs": _crumbs(gettext("Профиль")),
        "form": form,
        "saved": saved,
        "profile": profile,
        "roles": sorted(effective_roles(request.user)),
        "stats": {
            "favorites": Favorite.objects.filter(user=request.user).count(),
            "views": SavedView.objects.filter(user=request.user).count(),
            "comparisons": ComparisonSet.objects.filter(user=request.user).count(),
            "exports": ExportJob.objects.filter(user=request.user).count(),
        },
    }
    return render(request, "account/profile.html", ctx)


@login_required
def saved_views(request: HttpRequest) -> HttpResponse:
    """Список сохранённых видов пользователя + форма создания нового."""
    if request.method == "POST":
        form = SavedViewForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"]
            SavedView.objects.update_or_create(
                user=request.user,
                name=name,
                defaults={"config": form.to_config()},
            )
            record(request.user, f"saved_view:create {name}")
            return redirect("account_views")
    else:
        form = SavedViewForm()
    views = list(SavedView.objects.filter(user=request.user))
    okatos = [
        v.config["okato"] for v in views if isinstance(v.config, dict) and v.config.get("okato")
    ]
    names = region_names_ru(okatos)
    for view in views:
        cfg = view.config if isinstance(view.config, dict) else {}
        view.summary = _saved_view_summary(cfg, names.get(str(cfg.get("okato", "")), ""))
    ctx = {
        "active": "account",
        "cabinet_tab": "views",
        "breadcrumbs": _crumbs(gettext("Сохранённые виды")),
        "form": form,
        "views": views,
    }
    return render(request, "account/saved_views.html", ctx)


@login_required
def saved_view_open(request: HttpRequest, pk: int) -> HttpResponse:
    """Открыть сохранённый вид: реконструировать экран из конфига и перенаправить туда."""
    view = get_object_or_404(SavedView, pk=pk, user=request.user)
    return redirect(view.target_url())


@login_required
def saved_view_share(request: HttpRequest, pk: int) -> HttpResponse:
    """Включить или отозвать публичную ссылку на свой вид (только POST, только владелец)."""
    view = get_object_or_404(SavedView, pk=pk, user=request.user)
    if request.method == "POST":
        if view.is_shared:
            view.disable_sharing()
            record(request.user, f"saved_view:unshare {view.name}")
        else:
            view.enable_sharing()
            record(request.user, f"saved_view:share {view.name}")
    return redirect("account_views")


@login_required
def saved_view_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Удалить сохранённый вид (только свой; только POST)."""
    view = get_object_or_404(SavedView, pk=pk, user=request.user)
    if request.method == "POST":
        name = view.name
        view.delete()
        record(request.user, f"saved_view:delete {name}")
    return redirect("account_views")


@login_required
def export_history(request: HttpRequest) -> HttpResponse:
    """Экспорт-центр: быстрый экспорт региона, ярлыки из избранного и история заданий."""
    favorite_regions = [
        {"okato": fav.ref, "label": gettext(fav.label) if fav.label else fav.ref}
        for fav in Favorite.objects.filter(user=request.user, kind=Favorite.Kind.REGION)
    ]
    ctx = {
        "active": "account",
        "cabinet_tab": "exports",
        "breadcrumbs": _crumbs(gettext("Экспорт-центр")),
        "jobs": ExportJob.objects.filter(user=request.user),
        "favorite_regions": favorite_regions,
        "default_year": 2024,
        "year_range": range(2024, 2009, -1),
    }
    return render(request, "account/exports.html", ctx)


@login_required
@require_POST
def export_history_clear(request: HttpRequest) -> HttpResponse:
    """Очистить историю выгрузок: удалить задания экспорта пользователя и их файлы."""
    jobs = ExportJob.objects.filter(user=request.user)
    for job in jobs:
        if job.file:
            job.file.delete(save=False)
    count = jobs.count()
    jobs.delete()
    if count:
        record(request.user, "export:clear")
    return redirect("account_exports")


# Человекочитаемые подписи параметров сохранённого вида (config хранит слаги).
_VIEW_SCHEME_LABELS = {"equal": "Равные веса", "pca": "PCA", "expert": "Экспертные"}
_VIEW_MEASURE_LABELS = {"cluster": "Тип (кластер)", "index": "Индекс развития"}


def _saved_view_summary(config: dict[str, object], region_name: str) -> str:
    """Собрать краткое читаемое описание вида: год, карта/регион и схема весов."""
    parts = [gettext("Год %(year)s") % {"year": config.get("year", 2024)}]
    okato = config.get("okato")
    if okato:
        label = gettext(region_name) if region_name else str(okato)
        parts.append(gettext("Регион: %(name)s") % {"name": label})
    else:
        measure = str(config.get("measure", "cluster"))
        parts.append(
            gettext("Карта: %(measure)s")
            % {"measure": gettext(_VIEW_MEASURE_LABELS.get(measure, measure))}
        )
    scheme = str(config.get("scheme", "equal"))
    parts.append(
        gettext("Схема: %(scheme)s") % {"scheme": gettext(_VIEW_SCHEME_LABELS.get(scheme, scheme))}
    )
    return " · ".join(parts)


# ── Лента активности: человекочитаемое описание записей журнала аудита ──────────
# Действия хранятся кодами («auth:login», «export:xlsx okato=… year=…», «saved_view:create
# <имя>» и т.п.). Здесь код разбирается в локализованный текст и категорию (для иконки/цвета).
def _describe_action(action: str) -> tuple[str, str]:
    """Вернуть (категория, локализованный текст) для записи журнала аудита."""
    head, _, rest = action.partition(" ")
    rest = rest.strip()
    mapping = {
        "auth:login": ("auth", gettext("Вход в систему")),
        "auth:logout": ("auth", gettext("Выход из системы")),
        "feedback:submit": ("feedback", gettext("Отправлена обратная связь")),
    }
    if head in mapping:
        return mapping[head]
    if head.startswith("user:register"):
        return ("auth", gettext("Регистрация учётной записи"))
    if head == "export:xlsx":
        return ("export", gettext("Экспорт отчёта (XLSX)"))
    if head == "export:docx":
        return ("export", gettext("Экспорт отчёта (DOCX)"))
    if head == "saved_view:create":
        return ("view", gettext("Создан сохранённый вид «%(name)s»") % {"name": rest})
    if head == "saved_view:share":
        return ("view", gettext("Открыт публичный доступ к виду «%(name)s»") % {"name": rest})
    if head == "saved_view:unshare":
        return ("view", gettext("Закрыт публичный доступ к виду «%(name)s»") % {"name": rest})
    if head == "saved_view:delete":
        return ("view", gettext("Удалён сохранённый вид «%(name)s»") % {"name": rest})
    if head == "favorite:add":
        kind = rest.split(":", 1)[0]
        if kind == "metric":
            return ("favorite", gettext("Показатель добавлен в избранное"))
        return ("favorite", gettext("Регион добавлен в избранное"))
    if head == "favorite:remove":
        return ("favorite", gettext("Удалено из избранного"))
    if head == "comparison:save":
        return ("view", gettext("Сохранён набор сравнения «%(name)s»") % {"name": rest})
    if head == "comparison:delete":
        return ("view", gettext("Удалён набор сравнения «%(name)s»") % {"name": rest})
    if head == "settings:update":
        return ("other", gettext("Обновлены настройки отображения"))
    if head == "export:clear":
        return ("export", gettext("Очищена история выгрузок"))
    if head == "favorite:bulk_delete":
        return ("favorite", gettext("Удалено закладок: %(n)s") % {"n": rest})
    if head == "saved_view:bulk_delete":
        return ("view", gettext("Удалено видов: %(n)s") % {"n": rest})
    if head == "data:export":
        return ("other", gettext("Экспортированы личные данные"))
    return ("other", action)


def _activity_events(user: object, limit: int) -> list[dict[str, object]]:
    """Собрать последние события активности пользователя для ленты."""
    events = []
    for entry in AuditLog.objects.filter(user=user)[:limit]:
        category, text = _describe_action(entry.action)
        events.append({"ts": entry.ts, "category": category, "text": text})
    return events


def _localized_favorites(user: object) -> list[dict[str, object]]:
    """Закладки пользователя с локализованной подписью региона (показатели — как есть)."""
    items = []
    for fav in Favorite.objects.filter(user=user):
        label = fav.label or fav.ref
        # Имена регионов есть в каталоге переводов — локализуем по активному языку.
        if fav.kind == Favorite.Kind.REGION and label:
            label = gettext(label)
        items.append(
            {
                "id": fav.pk,
                "kind": fav.kind,
                "kind_display": fav.get_kind_display(),
                "label": label,
                "url": fav.target_url(),
                "created": fav.created,
            }
        )
    return items


@login_required
@require_POST
def favorite_toggle(request: HttpRequest) -> JsonResponse:
    """Переключить закладку (регион/показатель) для текущего пользователя.

    Идемпотентно по (пользователь, тип, ссылка): если закладка есть — снимается, иначе
    создаётся с денормализованной подписью. Возвращает актуальное состояние и счётчик.
    """
    kind = request.POST.get("kind", "")
    ref = request.POST.get("ref", "").strip()
    label = request.POST.get("label", "").strip()[:300]
    if kind not in {Favorite.Kind.REGION, Favorite.Kind.METRIC} or not ref:
        return JsonResponse({"error": "bad_request"}, status=400)
    existing = Favorite.objects.filter(user=request.user, kind=kind, ref=ref).first()
    if existing:
        existing.delete()
        record(request.user, f"favorite:remove {kind}:{ref}")
        favorited = False
    else:
        Favorite.objects.create(user=request.user, kind=kind, ref=ref, label=label)
        record(request.user, f"favorite:add {kind}:{ref}")
        favorited = True
    count = Favorite.objects.filter(user=request.user).count()
    return JsonResponse({"favorited": favorited, "count": count})


@login_required
def favorites_list(request: HttpRequest) -> HttpResponse:
    """Страница «Избранное»: закладки на регионы и показатели с переходом к объекту."""
    items = _localized_favorites(request.user)
    ctx = {
        "active": "account",
        "cabinet_tab": "favorites",
        "breadcrumbs": _crumbs(gettext("Избранное")),
        "regions": [i for i in items if i["kind"] == Favorite.Kind.REGION],
        "metrics": [i for i in items if i["kind"] == Favorite.Kind.METRIC],
    }
    return render(request, "account/favorites.html", ctx)


@login_required
def activity_feed(request: HttpRequest) -> HttpResponse:
    """Страница «Активность»: лента последних действий пользователя из журнала аудита."""
    ctx = {
        "active": "account",
        "cabinet_tab": "activity",
        "breadcrumbs": _crumbs(gettext("Активность")),
        "events": _activity_events(request.user, limit=100),
    }
    return render(request, "account/activity.html", ctx)


# ── Наборы сравнения: именованные группы регионов для страницы «Сравнение» ──
_OKATO_RE = re.compile(r"^\d{2,12}$")


def _comparison_display(user: object) -> list[dict[str, object]]:
    """Наборы сравнения пользователя с локализованными подписями регионов."""
    sets = list(ComparisonSet.objects.filter(user=user))
    all_okatos = sorted({o for cs in sets for o in (cs.okatos or [])})
    names = region_names_ru(all_okatos)
    out = []
    for cs in sets:
        regions = []
        for okato in cs.okatos or []:
            raw = names.get(okato, "")
            # Имена регионов есть в каталоге переводов — локализуем по активному языку.
            regions.append(gettext(raw) if raw else okato)
        out.append(
            {
                "id": cs.pk,
                "name": cs.name,
                "year": cs.year,
                "regions": regions,
                "url": cs.target_url(),
            }
        )
    return out


@login_required
def comparison_sets(request: HttpRequest) -> HttpResponse:
    """Страница «Наборы сравнения»: список сохранённых групп регионов с открытием/удалением."""
    ctx = {
        "active": "account",
        "cabinet_tab": "comparisons",
        "breadcrumbs": _crumbs(gettext("Наборы сравнения")),
        "sets": _comparison_display(request.user),
    }
    return render(request, "account/comparisons.html", ctx)


@login_required
@require_POST
def comparison_save(request: HttpRequest) -> JsonResponse:
    """Сохранить текущее сравнение как именованный набор (POST со страницы «Сравнение»).

    Принимает имя, список ОКАТО (2–3) и год; валидирует коды регионов строгим шаблоном.
    Обновляет набор с тем же именем (update_or_create), возвращает статус в JSON.
    """
    name = request.POST.get("name", "").strip()[:200]
    okatos = [o.strip() for o in request.POST.getlist("okato") if o.strip()]
    okatos = [o for o in okatos if _OKATO_RE.match(o)]
    # Уникализируем, сохраняя порядок.
    okatos = list(dict.fromkeys(okatos))
    try:
        year = int(request.POST.get("year", "2024"))
    except (TypeError, ValueError):
        year = 2024
    if not name or not (2 <= len(okatos) <= 3):
        return JsonResponse({"error": "bad_request"}, status=400)
    obj, _created = ComparisonSet.objects.update_or_create(
        user=request.user,
        name=name,
        defaults={"okatos": okatos, "year": year},
    )
    record(request.user, f"comparison:save {name}")
    return JsonResponse({"ok": True, "id": obj.pk, "name": name})


@login_required
def comparison_open(request: HttpRequest, pk: int) -> HttpResponse:
    """Открыть набор: перейти на страницу сравнения с предвыбранными регионами и годом."""
    cs = get_object_or_404(ComparisonSet, pk=pk, user=request.user)
    return redirect(cs.target_url())


@login_required
@require_POST
def comparison_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Удалить набор сравнения (только свой; только POST)."""
    cs = get_object_or_404(ComparisonSet, pk=pk, user=request.user)
    name = cs.name
    cs.delete()
    record(request.user, f"comparison:delete {name}")
    return redirect("account_comparisons")


@login_required
def settings_edit(request: HttpRequest) -> HttpResponse:
    """Настройки отображения: дефолтные год, схема весов и мера карты (применяются глобально)."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    saved = False
    if request.method == "POST":
        form = PreferencesForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            record(request.user, "settings:update")
            saved = True
    else:
        form = PreferencesForm(instance=profile)
    ctx = {
        "active": "account",
        "cabinet_tab": "settings",
        "breadcrumbs": _crumbs(gettext("Настройки")),
        "form": form,
        "saved": saved,
    }
    return render(request, "account/settings.html", ctx)


@login_required
@require_POST
def favorites_bulk_delete(request: HttpRequest) -> HttpResponse:
    """Массовое удаление закладок по списку идентификаторов (только свои)."""
    ids = request.POST.getlist("ids")
    qs = Favorite.objects.filter(user=request.user, pk__in=ids)
    count = qs.count()
    qs.delete()
    if count:
        record(request.user, f"favorite:bulk_delete {count}")
    return redirect("account_favorites")


@login_required
@require_POST
def saved_views_bulk_delete(request: HttpRequest) -> HttpResponse:
    """Массовое удаление сохранённых видов по списку идентификаторов (только свои)."""
    ids = request.POST.getlist("ids")
    qs = SavedView.objects.filter(user=request.user, pk__in=ids)
    count = qs.count()
    qs.delete()
    if count:
        record(request.user, f"saved_view:bulk_delete {count}")
    return redirect("account_views")


@login_required
def data_export(request: HttpRequest) -> HttpResponse:
    """Экспорт личных данных (избранное, виды, наборы, профиль) в JSON — «выгрузка моих данных»."""
    user = request.user
    profile = UserProfile.objects.filter(user=user).first()
    payload = {
        "username": user.get_username(),
        "email": user.email,
        "exported_at": timezone.now().isoformat(),
        "profile": {
            "organization": profile.organization if profile else "",
            "default_year": profile.default_year if profile else None,
            "default_scheme": profile.default_scheme if profile else None,
            "default_measure": profile.default_measure if profile else None,
        },
        "favorites": [
            {"kind": f.kind, "ref": f.ref, "label": f.label, "created": f.created.isoformat()}
            for f in Favorite.objects.filter(user=user)
        ],
        "saved_views": [
            {"name": v.name, "config": v.config, "created": v.created.isoformat()}
            for v in SavedView.objects.filter(user=user)
        ],
        "comparison_sets": [
            {"name": c.name, "okatos": c.okatos, "year": c.year, "created": c.created.isoformat()}
            for c in ComparisonSet.objects.filter(user=user)
        ],
    }
    record(user, "data:export")
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    response = HttpResponse(body, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="regionlens-my-data.json"'
    return response
