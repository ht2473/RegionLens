"""Management-команда ``refresh_data``: безопасное обновление витрины DuckDB.

Принимает свежую parquet-выгрузку коллекции Росстата (портал «Если быть точным»),
пересобирает всю аналитику офлайн-конвейером в отдельный staging-файл, независимо
проверяет результат и атомарно подменяет боевую витрину, сохранив резервную копию.
Боевая витрина недоступна для записи приложению и не затрагивается до самого
последнего шага: неудача на любом этапе оставляет её ровно в прежнем состоянии.

Использование:
    python backend/manage.py refresh_data --source path/to/выгрузка.parquet
    python backend/manage.py refresh_data              # взять свежайший *.parquet
                                                       # из каталога приёма (DATA_INCOMING_DIR)
    python backend/manage.py refresh_data --skip-ingest  # пересобрать из текущего сырья

Файл, взятый из каталога приёма, после успешного обновления перемещается в
``processed/`` — этим гасится условие срабатывания systemd path-юнита на сервере.
Требует установленных зависимостей конвейера (``pip install -e ".[pipeline]"``).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser


class Command(BaseCommand):
    """Обновить витрину DuckDB из parquet-выгрузки с проверкой и атомарной подменой."""

    help = (
        "Принять parquet-выгрузку, пересобрать конвейер в staging и атомарно "
        "подменить витрину DuckDB (с бэкапом и независимой проверкой результата)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Аргументы команды: источник, каталоги, глубина ротации бэкапов."""
        parser.add_argument(
            "--source",
            type=Path,
            default=None,
            help="Путь к входному parquet; без него берётся свежайший из каталога приёма.",
        )
        parser.add_argument(
            "--incoming-dir",
            type=Path,
            default=Path(settings.DATA_INCOMING_DIR),
            help="Каталог приёма выгрузок (по умолчанию — settings.DATA_INCOMING_DIR).",
        )
        parser.add_argument(
            "--skip-ingest",
            action="store_true",
            help="Не принимать новый файл: пересобрать витрину из текущего сырья.",
        )
        parser.add_argument(
            "--keep-backups",
            type=int,
            default=3,
            help="Сколько последних бэкапов витрины хранить (по умолчанию 3).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Оркестрация обновления: приём → сборка → проверка → бэкап → подмена."""
        # Импорт внутри handle: команда доступна и в web-установке (без extras
        # конвейера), а понятная ошибка возникает только при фактическом запуске.
        try:
            from pipeline import refresh
            from pipeline.logging_setup import configure_logging
        except ImportError as exc:  # pragma: no cover - зависит от состава окружения
            raise CommandError(
                "Для обновления витрины нужны зависимости конвейера: "
                'установите проект как `pip install -e ".[pipeline]"`.'
            ) from exc

        configure_logging()
        started = time.monotonic()

        target = Path(settings.DUCKDB_PATH)
        sources_path = Path(settings.SOURCES_REGISTRY)
        # Корень репозитория — из настроек, а не из положения реестра: SOURCES_REGISTRY
        # переопределяем через окружение, и выводить корень из его пути было бы хрупко.
        repo_root = Path(settings.REPO_ROOT)
        staging = target.parent / "staging" / target.name
        backups_dir = target.parent / "backups"
        keep = int(options["keep_backups"])

        source = options.get("source")
        skip_ingest = bool(options.get("skip_ingest"))
        from_incoming = False
        incoming_file: Path | None = None

        if not skip_ingest:
            if source is not None:
                incoming_file = Path(str(source))
            else:
                incoming_dir = Path(str(options["incoming_dir"]))
                candidates = sorted(incoming_dir.glob("*.parquet"), key=lambda p: p.stat().st_mtime)
                if not candidates:
                    raise CommandError(
                        f"В каталоге приёма нет выгрузок: {incoming_dir} "
                        "(положите *.parquet или укажите --source / --skip-ingest)."
                    )
                incoming_file = candidates[-1]
                from_incoming = True
                self.stdout.write(f"Каталог приёма: взят свежайший файл {incoming_file.name}")

        try:
            if incoming_file is not None:
                accepted = refresh.ingest_incoming(incoming_file, sources_path, repo_root)
                self.stdout.write(f"Выгрузка принята: {accepted}")

            self.stdout.write("Сборка конвейера в staging (боевая витрина не затрагивается)…")
            refresh.build_staging(staging, sources_path)

            summary = refresh.validate_staging(staging, target)
            self.stdout.write(
                "Проверка пройдена: регионов "
                f"{summary['regions']}, MAX(year)={summary['max_year']}."
            )

            backup = refresh.swap_store(staging, target, backups_dir, keep=keep)
        except refresh.RefreshError as exc:
            raise CommandError(f"Обновление отклонено, витрина не изменена: {exc}") from exc
        except PermissionError as exc:
            raise CommandError(
                "Не удалось подменить файл витрины — он занят другим процессом. "
                "На Windows остановите dev-сервер (runserver) на время обновления. "
                f"Системная ошибка: {exc}"
            ) from exc

        if from_incoming and incoming_file is not None:
            archived = refresh.archive_processed(incoming_file)
            self.stdout.write(f"Исходная выгрузка перемещена в архив: {archived}")

        # Текущий процесс переоткрывает соединение сразу; воркеры gunicorn подхватят
        # новую витрину сами — по смене сигнатуры файла (см. core.duck).
        from core import duck

        duck.reset_connection()

        elapsed = time.monotonic() - started
        self.stdout.write(
            self.style.SUCCESS(
                f"Витрина обновлена за {elapsed:.0f} с. "
                + (f"Бэкап прежней: {backup}" if backup else "Прежней витрины не было.")
            )
        )
