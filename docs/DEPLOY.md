# Развёртывание RegionLens на VPS

Инструкция по установке приложения на чистый виртуальный сервер (Ubuntu 22.04/24.04).
Конфигурация универсальна и не привязана к конкретному провайдеру: подойдёт любой VPS,
на котором можно установить Docker. Ориентир по ресурсам — от 2 ГБ RAM (базовый стек);
с включённым мониторингом (Prometheus + Grafana) рекомендуется 4 ГБ.

Боевой стек описан в `docker-compose.prod.yml`: nginx (точка входа) → приложение
(gunicorn) → PostgreSQL + Redis, плюс опциональный профиль `monitoring`.

---

## 1. Подготовка сервера

```bash
# от root или через sudo
apt update && apt upgrade -y

# Docker Engine + плагин compose (официальный скрипт)
curl -fsSL https://get.docker.com | sh

# Отдельный пользователь для приложения (не работать под root)
adduser --disabled-password --gecos "" regionlens
usermod -aG docker regionlens

# Базовый firewall: открыть только SSH и HTTP/HTTPS
apt install -y ufw
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

При 2 ГБ RAM добавьте swap — пересборка витрины (`refresh_data`, там pandas/sklearn)
и сборка образа требовательны к памяти:

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## 2. Код и данные

```bash
su - regionlens
git clone https://github.com/ht2473/RegionLens.git
cd RegionLens

# Аналитическая витрина DuckDB хранится в Git LFS — подтянуть реальный файл
# (иначе на его месте будет текстовый указатель):
apt-get install -y git-lfs   # один раз, от root
git lfs install
git lfs pull
```

## 3. Настройка окружения

```bash
cp .env.example .env
nano .env
```

Минимально необходимое для прода (секция PRODUCTION в `.env.example`):

| Переменная | Значение |
|---|---|
| `DJANGO_SECRET_KEY` | длинный случайный ключ: `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `DJANGO_ALLOWED_HOSTS` | ваш домен и/или IP, например `regionlens.example.com,203.0.113.10` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | со схемой, например `https://regionlens.example.com` |
| `DOMAIN` | домен для nginx, например `regionlens.example.com` |
| `POSTGRES_PASSWORD` | надёжный пароль БД |
| `HTTP_PORT` | `80`, если TLS терминирует хостовой прокси; иначе оставьте `8080` |

> **CSRF за прокси.** Без `DJANGO_CSRF_TRUSTED_ORIGINS` все POST-формы (вход, смена
> языка, избранное) вернут 403. Значение задаётся со схемой (`https://...`).

## 4. Запуск

```bash
# Базовый стек (nginx + app + postgres + redis):
docker compose -f docker-compose.prod.yml up -d --build

# Вместе с мониторингом (Prometheus + Grafana):
docker compose -f docker-compose.prod.yml --profile monitoring up -d --build
```

При старте контейнер приложения сам применяет миграции БД. Наполнение боевыми данными
выполняется отдельно (это НЕ автозапуск, чтобы не затирать реальные данные):

```bash
# Демонстрационные учётки и примеры (для показа/проверки):
docker compose -f docker-compose.prod.yml exec app python backend/manage.py seed_demo

# Учётная запись администратора:
docker compose -f docker-compose.prod.yml exec app python backend/manage.py createsuperuser
```

Проверка статуса: `curl http://localhost/healthz/` (или `:8080` при `HTTP_PORT=8080`)
должен вернуть `200 OK`.

## 5. TLS-сертификат (HTTPS)

nginx в стеке слушает 80/HTTP. HTTPS на боевом домене добавляют одним из способов:

- **Хостовой Caddy/Traefik перед стеком** (проще всего): reverse-proxy на хосте с
  автоматическим Let's Encrypt проксирует на `HTTP_PORT` этого стека. Тогда оставьте
  `HTTP_PORT=8080` и настройте автоматический сертификат на уровне хоста.
- **certbot рядом с nginx**: расширить сервис `nginx` томом сертификатов и вторым
  server-блоком на 443; получить сертификат `certbot certonly --webroot`.

`DJANGO_TRUST_PROXY_SSL=true` (по умолчанию в compose) обеспечивает корректные
HTTPS-редиректы и secure-cookies за терминирующим TLS прокси.

## 6. Обновление данных

Свежие parquet-выгрузки коллекции Росстата принимаются командой `refresh_data`
(проверка схемы → пересборка в staging → валидация → бэкап → атомарная подмена витрины;
воркеры подхватывают новый файл без рестарта). Подробно — в разделе «Обновление данных»
README. На VPS удобен каталог приёма `data/incoming/` + systemd path-юнит из
`deploy/systemd/` (запускает обновление при появлении `*.parquet`).

## 7. Обновление версии приложения

```bash
cd ~/RegionLens
git pull
git lfs pull                                   # если менялась витрина
docker compose -f docker-compose.prod.yml up -d --build
```

## 8. Резервное копирование

Единственные невоспроизводимые данные — пользовательское состояние в PostgreSQL
(аналитику пересобирает конвейер). Разовый дамп:

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U regionlens regionlens | gzip > backup_$(date +%F).sql.gz
```

**Автоматически (рекомендуется).** Скрипт `deploy/backup/pg_backup.sh` делает то же самое
в каталог `data/backups/postgres/` с ротацией (по умолчанию 7 последних; настраивается
переменными `BACKUP_DIR`, `KEEP_BACKUPS`). Запуск по расписанию — через systemd-таймер:

```bash
sudo cp deploy/systemd/regionlens-backup.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now regionlens-backup.timer   # ежедневно в 03:30
systemctl list-timers regionlens-backup.timer         # проверить расписание
journalctl -u regionlens-backup.service               # журнал последних прогонов
```

Восстановление:

```bash
gunzip -c backup_YYYY-MM-DD.sql.gz | docker compose -f docker-compose.prod.yml \
  exec -T postgres psql -U regionlens regionlens
```

## 9. Диагностика

```bash
docker compose -f docker-compose.prod.yml ps          # статус сервисов и healthcheck
docker compose -f docker-compose.prod.yml logs -f app # логи приложения
docker compose -f docker-compose.prod.yml logs -f nginx
```

Мониторинг (при запуске профиля `monitoring`): Grafana доступна на порту `3000`
(логин `admin`, пароль из `GRAFANA_PASSWORD`); наружу её лучше не публиковать —
пробрасывайте через SSH-туннель либо закройте firewall'ом.

## 10. Трекинг ошибок (Sentry / GlitchTip)

Необязательно, но полезно в проде: непойманные исключения уходят в приёмник ошибок со
стектрейсом и контекстом запроса. Поддерживается облачный **Sentry** и self-hosted
**GlitchTip** — протокол DSN один и тот же, меняется только адрес.

Включается одной переменной окружения (см. `.env.example`, секция «Трекинг ошибок»):

```bash
SENTRY_DSN=https://<key>@<host>/<project>   # пусто → трекинг выключен (dev/CI)
# SENTRY_ENVIRONMENT=production
# SENTRY_TRACES_SAMPLE_RATE=0.0             # 0.0 — только ошибки, без performance-трасс
```

Без `SENTRY_DSN` инициализация пропускается — никаких внешних вызовов. Персональные данные
(email, IP) наружу не отправляются (`send_default_pii=False`). Self-hosted GlitchTip
поднимается своим docker-compose рядом; в RegionLens достаточно указать его DSN.
