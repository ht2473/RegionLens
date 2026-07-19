"""Management-команда ``cleanup_exports``: чистка старых файлов экспорта из media/exports/.

Экспортные файлы (xlsx/docx/pdf) создаются синхронно и скачиваются пользователем сразу —
храниться вечно им незачем, а каталог экспорта иначе растёт бесконтрольно (это единственный
источник неограниченного роста диска в проде). Команда делает две вещи:

  1. TTL — удаляет задания экспорта старше N дней вместе с их файлами;
  2. сироты — подчищает файлы в exports/ без записи ExportJob (остаются, например, после
     каскадного удаления аккаунта: строки уходят, а файлы на диске — нет).

Безопасно повторяема; ``--dry-run`` показывает, что было бы удалено, ничего не трогая.

Использование:
    python backend/manage.py cleanup_exports              # старше 30 дней
    python backend/manage.py cleanup_exports --days 7
    python backend/manage.py cleanup_exports --dry-run
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import ExportJob

_EXPORTS_DIR = "exports"


def _safe_size(field: Any) -> int:
    """Размер файла поля или 0, если файла уже нет / хранилище не отдаёт размер."""
    try:
        return int(field.size)
    except (OSError, ValueError, NotImplementedError):
        return 0


def _storage_size(path: str) -> int:
    try:
        return int(default_storage.size(path))
    except (OSError, ValueError, NotImplementedError):
        return 0


def _modified_before(path: str, cutoff: datetime) -> bool:
    """Файл изменён раньше cutoff? При недоступности времени считаем, что нет (не трогаем)."""
    try:
        return bool(default_storage.get_modified_time(path) < cutoff)
    except (OSError, NotImplementedError, ValueError):
        return False


class Command(BaseCommand):
    help = "Удаляет старые задания экспорта и файлы-сироты из media/exports/."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="хранить экспорты не старше N дней (по умолчанию 30)",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="только показать, ничего не удалять"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        days: int = options["days"]
        dry: bool = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=days)
        freed = 0

        # 1) TTL: старые задания экспорта вместе с их файлами.
        jobs_removed = 0
        for job in ExportJob.objects.filter(created__lt=cutoff).iterator():
            if job.file:
                freed += _safe_size(job.file)
                if not dry:
                    job.file.delete(save=False)
            if not dry:
                job.delete()
            jobs_removed += 1

        # 2) Файлы-сироты в exports/ старше cutoff (без ссылки из ExportJob).
        referenced = set(ExportJob.objects.exclude(file="").values_list("file", flat=True))
        orphans_removed = 0
        try:
            _, files = default_storage.listdir(_EXPORTS_DIR)
        except (FileNotFoundError, NotImplementedError):
            files = []
        for name in files:
            path = f"{_EXPORTS_DIR}/{name}"
            if path in referenced or not _modified_before(path, cutoff):
                continue
            freed += _storage_size(path)
            if not dry:
                default_storage.delete(path)
            orphans_removed += 1

        prefix = "[dry-run] " if dry else ""
        self.stdout.write(
            f"{prefix}удалено заданий: {jobs_removed}, файлов-сирот: {orphans_removed}, "
            f"освобождено ~{freed // 1024} КБ (порог: старше {days} дн.)"
        )
