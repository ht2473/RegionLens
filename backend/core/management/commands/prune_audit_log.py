"""Management-команда ``prune_audit_log``: ретеншн журнала аудита.

Журнал аудита (``AuditLog``) пишется на каждое значимое действие и со временем растёт.
Есть точечное удаление по пользователю, но нет ретеншна по времени — эта команда его даёт:
удаляет записи старше N дней (по умолчанию 365 — хранит год). Безопасно повторяема;
``--dry-run`` показывает объём, ничего не удаляя.

Использование:
    python backend/manage.py prune_audit_log              # старше 365 дней
    python backend/manage.py prune_audit_log --days 180
    python backend/manage.py prune_audit_log --dry-run
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import AuditLog


class Command(BaseCommand):
    help = "Удаляет записи журнала аудита старше N дней."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=365,
            help="хранить аудит не старше N дней (по умолчанию 365)",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="только показать, ничего не удалять"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        days: int = options["days"]
        dry: bool = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=days)

        old = AuditLog.objects.filter(ts__lt=cutoff)
        count = old.count()
        if not dry:
            old.delete()

        prefix = "[dry-run] " if dry else ""
        self.stdout.write(f"{prefix}удалено записей аудита: {count} (старше {days} дн.)")
