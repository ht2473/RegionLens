"""Тесты Django admin: регистрация моделей, доступ к страницам, спецповедение.

Проверяем: все пять операционных моделей зарегистрированы; их changelist открывается у
суперпользователя (200); журнал аудита — только для чтения; предпросмотр текста обратной
связи усекается; массовое действие «пометить обработанными» работает.
"""

from __future__ import annotations

import pytest
from core.admin import AuditLogAdmin, FeedbackMessageAdmin
from core.models import AuditLog, ExportJob, FeedbackMessage, SavedView, UserProfile
from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import Client, RequestFactory
from django.urls import reverse

pytestmark = pytest.mark.django_db

_MODELS = [UserProfile, SavedView, FeedbackMessage, ExportJob, AuditLog]


@pytest.fixture
def admin_client() -> Client:
    """Клиент, авторизованный суперпользователем."""
    su = User.objects.create_superuser("root", "root@example.com", "Sl0transit-9")
    client = Client()
    client.force_login(su)
    return client


def _request_with_messages() -> RequestFactory:
    request = RequestFactory().post("/admin/")
    request.session = {}  # type: ignore[attr-defined]
    request._messages = FallbackStorage(request)  # type: ignore[attr-defined]
    return request


def test_all_models_registered() -> None:
    """Пять операционных моделей зарегистрированы в админке."""
    for model in _MODELS:
        assert model in admin.site._registry


def test_admin_changelists_open(admin_client: Client) -> None:
    """Список объектов каждой модели открывается у суперпользователя (200)."""
    for model in _MODELS:
        url = reverse(f"admin:core_{model.__name__.lower()}_changelist")
        assert admin_client.get(url).status_code == 200, model.__name__


def test_auditlog_admin_is_view_only() -> None:
    """Журнал аудита нельзя создавать/править вручную (append-only)."""
    audit_admin = AuditLogAdmin(AuditLog, admin.site)
    request = RequestFactory().get("/admin/")
    assert audit_admin.has_add_permission(request) is False
    assert audit_admin.has_change_permission(request) is False


def test_feedback_text_preview_truncates() -> None:
    """Длинный текст обратной связи усекается до 70 символов с многоточием."""
    fb_admin = FeedbackMessageAdmin(FeedbackMessage, admin.site)
    assert fb_admin.text_preview(FeedbackMessage(text="коротко")) == "коротко"
    preview = fb_admin.text_preview(FeedbackMessage(text="x" * 100))
    assert preview.endswith("…")
    assert len(preview) == 71  # 70 символов + многоточие


def test_feedback_mark_handled_action() -> None:
    """Массовое действие помечает выбранные сообщения обработанными."""
    fb = FeedbackMessage.objects.create(text="есть баг", is_handled=False)
    fb_admin = FeedbackMessageAdmin(FeedbackMessage, admin.site)
    fb_admin.mark_handled(_request_with_messages(), FeedbackMessage.objects.all())
    fb.refresh_from_db()
    assert fb.is_handled is True
