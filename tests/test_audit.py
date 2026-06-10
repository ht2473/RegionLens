"""Тесты журналирования действий (Ф10·7): вход/выход, регистрация, экспорт, виды, обратная связь.

Проверяем, что ключевые операционные события создают записи в AuditLog (с привязкой к
пользователю либо без неё для анонима), и что обратная связь теперь сохраняется в БД.
"""

from __future__ import annotations

from typing import Any

import pytest
from core.audit import record
from core.models import AuditLog, FeedbackMessage, SavedView
from django.contrib.auth.models import AnonymousUser, User
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

_PW = "Sl0transit-9"

_SAMPLE: dict[str, Any] = {
    "okato": "45000000",
    "year": 2024,
    "region_name": "Москва",
    "federal_district": "Центральный",
    "index": {
        "total_score": 87.3,
        "domains": [{"domain": "economy", "score": 1.2, "score_prev": 1.0, "delta": 0.2}],
    },
    "cluster": {"cluster_id": 2, "cluster_label": "высокие доходы"},
    "shap_top": [{"metric_id": 1, "metric_name": "Доходы", "shap_value": 0.12}],
    "rank": {"rank": 1, "of": 85},
}


def test_login_and_logout_logged(client: Client) -> None:
    """Вход и выход фиксируются в аудите."""
    User.objects.create_user("li", password=_PW)
    client.login(username="li", password=_PW)
    assert AuditLog.objects.filter(action="auth:login").exists()
    client.logout()
    assert AuditLog.objects.filter(action="auth:logout").exists()


def test_register_logged(client: Client) -> None:
    """Регистрация фиксируется в аудите."""
    client.post(reverse("register"), {"username": "reg", "password1": _PW, "password2": _PW})
    assert AuditLog.objects.filter(action__startswith="user:register").exists()


def test_export_logged(
    client: Client, monkeypatch: pytest.MonkeyPatch, settings: Any, tmp_path: Any
) -> None:
    """Экспорт отчёта фиксируется в аудите с привязкой к пользователю."""
    settings.MEDIA_ROOT = str(tmp_path)
    monkeypatch.setattr("core.queries.region_dashboard", lambda okato, year: _SAMPLE)
    user = User.objects.create_user("ex", password=_PW)
    client.force_login(user)
    client.get("/regions/45000000/export/?format=xlsx&year=2024")
    assert AuditLog.objects.filter(user=user, action__startswith="export:xlsx").exists()


def test_saved_view_create_and_delete_logged(client: Client) -> None:
    """Создание и удаление сохранённого вида фиксируются в аудите."""
    user = User.objects.create_user("sv", password=_PW)
    client.force_login(user)
    client.post(
        reverse("account_views"),
        {"name": "v1", "year": "2024", "measure": "index", "scheme": "equal"},
    )
    assert AuditLog.objects.filter(user=user, action__startswith="saved_view:create").exists()
    sv = SavedView.objects.get(user=user, name="v1")
    client.post(reverse("account_view_delete", args=[sv.pk]))
    assert AuditLog.objects.filter(user=user, action__startswith="saved_view:delete").exists()


def test_feedback_persists_and_logged(client: Client) -> None:
    """Обратная связь от вошедшего сохраняется в БД и фиксируется в аудите."""
    user = User.objects.create_user("fb", password=_PW)
    client.force_login(user)
    client.post(reverse("feedback"), {"text": "есть замечание"})
    assert FeedbackMessage.objects.filter(user=user, text__contains="замечание").exists()
    assert AuditLog.objects.filter(user=user, action="feedback:submit").exists()


def test_anonymous_feedback_has_no_user(client: Client) -> None:
    """Анонимная обратная связь сохраняется без пользователя; имя уходит в текст."""
    client.post(reverse("feedback"), {"text": "аноним пишет", "name": "Гость"})
    fb = FeedbackMessage.objects.get(text__contains="аноним пишет")
    assert fb.user is None
    assert "Гость" in fb.text
    assert AuditLog.objects.filter(user__isnull=True, action="feedback:submit").exists()


def test_record_truncates_and_handles_anonymous() -> None:
    """record усекает действие до лимита поля и пишет анонима без пользователя."""
    record(AnonymousUser(), "x" * 200)
    entry = AuditLog.objects.get(user__isnull=True)
    assert entry.action == "x" * 120
