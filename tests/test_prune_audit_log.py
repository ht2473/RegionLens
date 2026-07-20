"""Тесты команды prune_audit_log: ретеншн журнала аудита по времени и dry-run."""

from __future__ import annotations

from datetime import timedelta

import pytest
from core.models import AuditLog
from django.core.management import call_command
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _make_entry(action: str, *, age_days: int) -> AuditLog:
    """Создать запись аудита и «состарить» её ts на age_days назад (обойти auto_now_add)."""
    entry = AuditLog.objects.create(action=action)
    old = timezone.now() - timedelta(days=age_days)
    AuditLog.objects.filter(pk=entry.pk).update(ts=old)
    return entry


def test_prune_removes_old_keeps_recent() -> None:
    old = _make_entry("login", age_days=400)
    recent = _make_entry("export:pdf", age_days=10)

    call_command("prune_audit_log", "--days", "365")

    assert not AuditLog.objects.filter(pk=old.pk).exists()
    assert AuditLog.objects.filter(pk=recent.pk).exists()


def test_dry_run_changes_nothing() -> None:
    old = _make_entry("login", age_days=400)

    call_command("prune_audit_log", "--days", "365", "--dry-run")

    assert AuditLog.objects.filter(pk=old.pk).exists()
