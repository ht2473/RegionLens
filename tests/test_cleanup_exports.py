"""Тесты команды cleanup_exports: TTL старых заданий, подчистка файлов-сирот, dry-run."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest
from core.models import ExportJob
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _make_job(user, name: str, *, age_days: int) -> ExportJob:
    """Создать задание экспорта с файлом и «состарить» его created на age_days назад."""
    job = ExportJob.objects.create(user=user, okato="45000000", fmt="xlsx")
    job.file.save(name, ContentFile(b"export-bytes"), save=True)
    old = timezone.now() - timedelta(days=age_days)
    ExportJob.objects.filter(pk=job.pk).update(created=old)  # обойти auto_now_add
    return job


def test_cleanup_removes_old_keeps_recent(settings, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings.MEDIA_ROOT = str(tmp_path)
    user = get_user_model().objects.create_user("exporter", password="x")

    old_job = _make_job(user, "old.xlsx", age_days=40)
    recent_job = _make_job(user, "recent.xlsx", age_days=3)
    old_path = Path(old_job.file.path)
    recent_path = Path(recent_job.file.path)

    # файл-сирота (нет записи ExportJob), состаренный по mtime
    orphan = tmp_path / "exports" / "orphan.xlsx"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"orphan-bytes")
    past = (timezone.now() - timedelta(days=40)).timestamp()
    os.utime(orphan, (past, past))

    call_command("cleanup_exports", "--days", "30")

    # старое задание и его файл удалены; свежее — на месте
    assert not ExportJob.objects.filter(pk=old_job.pk).exists()
    assert not old_path.exists()
    assert ExportJob.objects.filter(pk=recent_job.pk).exists()
    assert recent_path.exists()
    # файл-сирота удалён
    assert not orphan.exists()


def test_dry_run_changes_nothing(settings, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings.MEDIA_ROOT = str(tmp_path)
    user = get_user_model().objects.create_user("exporter2", password="x")
    old_job = _make_job(user, "old.xlsx", age_days=40)
    old_path = Path(old_job.file.path)

    call_command("cleanup_exports", "--days", "30", "--dry-run")

    # dry-run: ничего не удалено
    assert ExportJob.objects.filter(pk=old_job.pk).exists()
    assert old_path.exists()


def test_recent_orphan_is_kept(settings, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Свежий файл-сирота (моложе порога) не трогается."""
    settings.MEDIA_ROOT = str(tmp_path)
    orphan = tmp_path / "exports" / "fresh-orphan.xlsx"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"fresh")

    call_command("cleanup_exports", "--days", "30")

    assert orphan.exists()
