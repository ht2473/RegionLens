"""Личный кабинет (Ф10·5): обзор, профиль, сохранённые виды, история экспортов.

Все страницы требуют входа (`login_required`) и показывают данные ТОЛЬКО текущего
пользователя — операционные модели фильтруются по `request.user` (изоляция владельца).
Смена пароля реализована штатными PasswordChange[Done]View в `urls.py`.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .audit import record
from .forms import ProfileForm, SavedViewForm
from .models import ExportJob, SavedView, UserProfile
from .permissions import effective_roles

_ACCOUNT_CRUMB = {"title": "Личный кабинет", "url": "/account/"}


def _crumbs(tail_title: str) -> list[dict[str, str | None]]:
    """Крошки кабинета: Главная → Личный кабинет → <раздел>."""
    return [
        {"title": "Главная", "url": reverse("home")},
        dict(_ACCOUNT_CRUMB),
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
            {"title": "Главная", "url": reverse("home")},
            {"title": "Личный кабинет", "url": None},
        ],
        "profile": profile,
        "roles": sorted(effective_roles(request.user)),
        "saved_count": SavedView.objects.filter(user=request.user).count(),
        "export_count": ExportJob.objects.filter(user=request.user).count(),
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
        "breadcrumbs": _crumbs("Профиль"),
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
        "breadcrumbs": _crumbs("Сохранённые виды"),
        "form": form,
        "views": SavedView.objects.filter(user=request.user),
    }
    return render(request, "account/saved_views.html", ctx)


@login_required
def saved_view_open(request: HttpRequest, pk: int) -> HttpResponse:
    """Открыть сохранённый вид: реконструировать экран из конфига и перенаправить туда."""
    view = get_object_or_404(SavedView, pk=pk, user=request.user)
    config = view.config or {}
    year = config.get("year", 2024)
    okato = config.get("okato")
    if okato:
        return redirect(f"{reverse('region-dashboard-page', args=[okato])}?year={year}")
    measure = config.get("measure", "cluster")
    return redirect(f"{reverse('map')}?year={year}&measure={measure}")


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
        "breadcrumbs": _crumbs("История экспортов"),
        "jobs": ExportJob.objects.filter(user=request.user),
    }
    return render(request, "account/exports.html", ctx)
