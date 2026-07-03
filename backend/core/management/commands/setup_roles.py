"""Management-команда: создать роли (группы) viewer/analyst/admin и назначить права.

Роли проекта — штатные Django `Group` + `Permission` с иерархией
viewer ⊂ analyst ⊂ admin. Тир-доступ (например, расширенная аналитика для analyst)
проверяется классами из `core.permissions` по членству в группе; здесь группам назначаются
МОДЕЛЬНЫЕ права операционных моделей — для корректной работы ORM и админки:
  • viewer / analyst — личные функции: свои сохранённые виды, экспорт, обратная связь, профиль;
  • admin — все права приложения `core` (управление обратной связью, просмотр аудита и т.д.).
analyst отличается от viewer не модельными правами, а тиром (расширенная аналитика Ф8/Ф9).

Идемпотентна: повторный запуск не плодит дубликаты и приводит состав прав к плану.
Требует выполненного `migrate` (модельные права создаются после миграций).

Использование:
    python backend/manage.py setup_roles
"""

from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from core.permissions import ROLE_ADMIN, ROLE_ANALYST, ROLE_VIEWER

try:
    from pipeline.logging_setup import log
except ImportError:  # pragma: no cover — конвейер недоступен (голый backend-чекаут)
    import structlog

    log = structlog.get_logger()

# Модельные права viewer/analyst: личные виды, экспорт, обратная связь, свой профиль.
_VIEWER_CODENAMES: list[str] = [
    "add_savedview",
    "change_savedview",
    "delete_savedview",
    "view_savedview",
    "add_exportjob",
    "view_exportjob",
    "add_feedbackmessage",
    "view_userprofile",
    "change_userprofile",
]


class Command(BaseCommand):
    """Создать/обновить роли viewer/analyst/admin и назначить им права (идемпотентно)."""

    help = "Создать/обновить роли viewer/analyst/admin и назначить права (идемпотентно)."

    def handle(self, *args: object, **options: object) -> None:
        """Привести группы и их права к плану; отчёт в stdout и structlog."""
        viewer_perms = list(
            Permission.objects.filter(
                content_type__app_label="core", codename__in=_VIEWER_CODENAMES
            )
        )
        admin_perms = list(Permission.objects.filter(content_type__app_label="core"))

        # analyst получает тот же модельный набор, что viewer; отличие — тир (см. docstring).
        plan: dict[str, list[Permission]] = {
            ROLE_VIEWER: viewer_perms,
            ROLE_ANALYST: viewer_perms,
            ROLE_ADMIN: admin_perms,
        }

        for name, perms in plan.items():
            group, created = Group.objects.get_or_create(name=name)
            group.permissions.set(perms)
            log.info("setup_roles", stage="ф10", role=name, created=created, perms=len(perms))
            verb = "создана" if created else "обновлена"
            self.stdout.write(f"{verb} группа «{name}» — назначено прав: {len(perms)}")

        if not viewer_perms:
            self.stderr.write(
                "ВНИМАНИЕ: модельные права приложения core не найдены. "
                "Сначала выполните `python backend/manage.py migrate`, затем setup_roles."
            )
