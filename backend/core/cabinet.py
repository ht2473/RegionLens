"""Личный кабинет (Ф10·5): обзор, профиль, сохранённые виды, история экспортов.

Все страницы требуют входа (`login_required`) и показывают данные ТОЛЬКО текущего
пользователя — операционные модели фильтруются по `request.user` (изоляция владельца).
Смена пароля реализована штатными PasswordChange[Done]View в `urls.py`.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from .audit import record
from .forms import ProfileForm, SavedViewForm
from .models import AuditLog, ExportJob, Favorite, SavedView, UserProfile
from .permissions import effective_roles


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
        "recent_activity": _activity_events(request.user, limit=6),
        "recent_favorites": _localized_favorites(request.user)[:6],
    }
    return render(request, "account/overview.html", ctx)


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
    ctx = {
        "active": "account",
        "cabinet_tab": "views",
        "breadcrumbs": _crumbs(gettext("Сохранённые виды")),
        "form": form,
        "views": SavedView.objects.filter(user=request.user),
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
    """История заданий экспорта пользователя (со ссылками на готовые файлы)."""
    ctx = {
        "active": "account",
        "cabinet_tab": "exports",
        "breadcrumbs": _crumbs(gettext("История экспортов")),
        "jobs": ExportJob.objects.filter(user=request.user),
    }
    return render(request, "account/exports.html", ctx)


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
