"""Тест скрипта резервного копирования PostgreSQL: создание дампа и ротация.

Гоняет реальный deploy/backup/pg_backup.sh, подменив `docker` заглушкой (печатает фиктивный
дамп вместо pg_dump) — так проверяется сам скрипт end-to-end без настоящего Postgres. На
платформах без bash (напр. Windows) тест пропускается.
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "backup" / "pg_backup.sh"
_BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(_BASH is None, reason="нет bash (напр. Windows)")


def _fake_docker(bindir: Path) -> None:
    """Заглушка docker на PATH: любой вызов печатает фиктивный дамп (вместо pg_dump)."""
    fake = bindir / "docker"
    fake.write_text('#!/usr/bin/env bash\necho "FAKE DUMP"\n')
    fake.chmod(0o755)


def test_backup_creates_gzip_and_rotates(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _fake_docker(bindir)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # Две «старые» копии с более ранним временем изменения — их должна затронуть ротация.
    old1 = backup_dir / "regionlens-20260101-000000.sql.gz"
    old2 = backup_dir / "regionlens-20260102-000000.sql.gz"
    for p in (old1, old2):
        p.write_bytes(b"old")
    past = time.time() - 100
    os.utime(old1, (past, past))
    os.utime(old2, (past + 1, past + 1))

    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "BACKUP_DIR": str(backup_dir),
        "KEEP_BACKUPS": "2",
    }
    result = subprocess.run(
        [_BASH, str(_SCRIPT)], env=env, capture_output=True, text=True, check=True
    )
    assert "Бэкап готов" in result.stdout

    dumps = sorted(backup_dir.glob("regionlens-*.sql.gz"))
    # было 2 старых + 1 новый = 3; ротация (KEEP=2) оставила 2 свежих
    assert len(dumps) == 2
    assert not old1.exists()  # самый старый удалён

    # свежий дамп — валидный gzip с содержимым (фиктивного) pg_dump
    newest = max(dumps, key=lambda p: p.stat().st_mtime)
    assert b"FAKE DUMP" in gzip.decompress(newest.read_bytes())
