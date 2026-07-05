"""Management-команда `seed_demo`: демонстрационное наполнение для запуска «из коробки».

Создаёт роли (через `setup_roles`) и демонстрационных пользователей трёх уровней доступа
с известными паролями, а также минимальный контент личного кабинета — чтобы после
`migrate` приложение поднималось готовым к показу без ручной подготовки данных.

Идемпотентна: повторный запуск не плодит дубликаты, приводит членство в группах и пароли
демо-учёток к плану.

Использование:
    python backend/manage.py migrate
    python backend/manage.py seed_demo
    python backend/manage.py seed_demo --password СВОЙ_ПАРОЛЬ   # общий пароль для всех демо-учёток

ВНИМАНИЕ: учётные записи и пароли — демонстрационные, только для локального показа и проверки.
В боевой среде их следует отключить или сменить пароли.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.models import SavedView
from core.permissions import ROLE_ADMIN, ROLE_ANALYST, ROLE_VIEWER

try:
    from pipeline.logging_setup import log
except ImportError:  # pragma: no cover — конвейер недоступен (голый backend-чекаут)
    import structlog

    log = structlog.get_logger()


# План демо-учёток: логин → (роль-группа, пароль по умолчанию, доступ в админку).
# is_staff/is_superuser выдаются только администратору — для полноценной работы админ-панели.
_DEMO_USERS: dict[str, dict[str, Any]] = {
    "demo_viewer": {"group": ROLE_VIEWER, "password": "viewer-demo-2025", "staff": False},
    "demo_analyst": {"group": ROLE_ANALYST, "password": "analyst-demo-2025", "staff": False},
    "demo_admin": {"group": ROLE_ADMIN, "password": "admin-demo-2025", "staff": True},
}


class Command(BaseCommand):
    """Создать демо-пользователей трёх ролей и минимальный контент кабинета (идемпотентно)."""

    help = "Демо-наполнение: пользователи viewer/analyst/admin и минимальный контент кабинета."

    def add_arguments(self, parser: Any) -> None:
        """Необязательный общий пароль для всех демо-учёток (иначе — пароли по умолчанию)."""
        parser.add_argument(
            "--password",
            dest="password",
            default=None,
            help="Задать единый пароль для всех демо-учёток вместо паролей по умолчанию.",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Обеспечить роли, создать/обновить демо-пользователей и демо-контент; отчёт в stdout."""
        # 1. Роли и их права должны существовать до назначения пользователям.
        call_command("setup_roles")

        raw_override = options.get("password")
        override_password = str(raw_override) if raw_override else None
        created_rows: list[tuple[str, str, str]] = []

        for username, spec in _DEMO_USERS.items():
            password = override_password or str(spec["password"])
            user, created = User.objects.get_or_create(username=username)

            # Приводим флаги и пароль к плану на каждом запуске (идемпотентность).
            user.is_staff = bool(spec["staff"])
            user.is_superuser = bool(spec["staff"])  # админ получает полный доступ к админ-панели
            user.set_password(password)
            user.save()

            group = Group.objects.get(name=str(spec["group"]))
            user.groups.set([group])

            created_rows.append((username, str(spec["group"]), password))
            log.info("seed_demo", stage="users", user=username, role=spec["group"], created=created)

        self._seed_cabinet_content()

        # Итоговая сводка учётных данных — удобно перенести во введение работы.
        self.stdout.write("")
        self.stdout.write("Демо-учётные записи (только для локального показа):")
        self.stdout.write(f"  {'логин':<14} {'роль':<10} пароль")
        for username, role, password in created_rows:
            self.stdout.write(f"  {username:<14} {role:<10} {password}")

    def _seed_cabinet_content(self) -> None:
        """Минимальный контент кабинета: по одному сохранённому виду для viewer и analyst.

        Конфигурация вида — только параметры экрана (год/схема/мера), без привязки к
        конкретному региону, поэтому безопасна независимо от наличия аналитических данных.
        """
        demo_view_config = {"year": 2024, "scheme": "equal", "measure": "index"}
        for username in ("demo_viewer", "demo_analyst"):
            user = User.objects.get(username=username)
            SavedView.objects.get_or_create(
                user=user,
                name="Пример: рейтинг развития, 2024",
                defaults={"config": demo_view_config},
            )
