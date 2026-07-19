#!/usr/bin/env bash
#
# Резервное копирование PostgreSQL RegionLens: pg_dump из контейнера postgres в gzip-файл
# с ротацией (хранится N последних). Единственные невоспроизводимые данные — пользовательское
# состояние (аккаунты, избранное, экспорты, аудит); аналитику пересобирает конвейер.
#
# Запуск вручную из каталога проекта:
#   deploy/backup/pg_backup.sh
# Или по расписанию — через systemd (deploy/systemd/regionlens-backup.timer, см. DEPLOY.md §8).
#
# Настройки через окружение (значения по умолчанию совпадают с docker-compose.prod.yml):
#   COMPOSE_FILE   файл compose               (docker-compose.prod.yml)
#   BACKUP_DIR     каталог для дампов          (data/backups/postgres)
#   KEEP_BACKUPS   сколько последних хранить   (7)
#   POSTGRES_USER  пользователь БД             (regionlens)
#   POSTGRES_DB    имя базы                    (regionlens)
#
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-data/backups/postgres}"
KEEP_BACKUPS="${KEEP_BACKUPS:-7}"
POSTGRES_USER="${POSTGRES_USER:-regionlens}"
POSTGRES_DB="${POSTGRES_DB:-regionlens}"

mkdir -p "$BACKUP_DIR"
timestamp="$(date +%Y%m%d-%H%M%S)"
outfile="$BACKUP_DIR/regionlens-$timestamp.sql.gz"
tmpfile="$outfile.partial"

# Дамп с --clean --if-exists: восстановление на существующую базу не спотыкается об объекты.
# Пишем во временный файл и переименовываем в конце — незавершённый дамп не попадёт в ротацию.
docker compose -f "$COMPOSE_FILE" exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
  | gzip >"$tmpfile"

mv "$tmpfile" "$outfile"

# Ротация: удалить всё, кроме KEEP_BACKUPS самых свежих (по времени изменения).
# shellcheck disable=SC2012
ls -1t "$BACKUP_DIR"/regionlens-*.sql.gz 2>/dev/null | tail -n +"$((KEEP_BACKUPS + 1))" | while read -r old; do
  rm -f -- "$old"
done

echo "Бэкап готов: $outfile (храним последних: $KEEP_BACKUPS)"
