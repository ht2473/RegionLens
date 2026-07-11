"""Настройки Django-проекта RegionLens.

Значения берутся из окружения (django-environ) — без хардкода. Реальные значения
задаются в .env / docker-compose; здесь — безопасные значения по умолчанию, чтобы
приложение поднималось «из коробки» (`python main.py`) даже без сконфигурированного
.env. Боевое развёртывание ОБЯЗАТЕЛЬНО переопределяет SECRET_KEY/DEBUG/DATABASE_URL.
"""

from pathlib import Path

import environ

# backend/config/settings.py -> BASE_DIR = backend/ ; REPO_ROOT — корень репозитория.
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

env = environ.Env()
# .env читается из корня репозитория, если присутствует (необязателен).
environ.Env.read_env(REPO_ROOT / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0"])

# OLTP: PostgreSQL через DATABASE_URL. По умолчанию — локальный sqlite-fallback, чтобы
# tooling и первый запуск работали без поднятого Postgres. Прод/dev используют Postgres.
_default_db = "sqlite:///" + str(REPO_ROOT / "db.sqlite3")
DATABASES = {"default": env.db("DATABASE_URL", default=_default_db)}

# OLAP: путь к DuckDB-файлу (read-only из приложения; владелец — конвейер).
DUCKDB_PATH = env("DUCKDB_PATH", default=str(REPO_ROOT / "data" / "regionlens.duckdb"))
# Каталог обученных ML-моделей (карточки читает витрина «Модели»).
MODELS_DIR = env("MODELS_DIR", default=str(REPO_ROOT / "models"))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_prometheus",
    "rest_framework",
    "drf_spectacular",
    "core",
]

MIDDLEWARE = [
    # Метрики Prometheus: Before — самым первым, After — самым последним (охватывают весь запрос).
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Отдача статики в проде (сжатие + кэш-заголовки); должен идти сразу за SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "core.middleware.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Определяет активный язык запроса (cookie django_language, затем заголовок Accept-Language).
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "core.context_processors.user_preferences",
                "core.context_processors.user_roles",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

# Поддерживаемые языки интерфейса. Исходные строки заданы на русском (msgid),
# каталог en/ содержит их перевод на английский.
LANGUAGES = [
    ("ru", "Русский"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = REPO_ROOT / "staticfiles"

# В проде статику отдаёт WhiteNoise: сжатие и хешированные имена (кэш-бастинг) через манифест.
# В DEBUG — обычное (нехешированное) хранилище: манифест требует предварительного collectstatic,
# которым локальная разработка обычно не занимается; условие ниже даёт корректную работу
# {% static %} без лишнего шага и в dev, и в проде.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = REPO_ROOT / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DRF: сессионная аутентификация (не JWT) + схема drf-spectacular.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.api.authentication.ApiTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Единый конверт ошибок + логирование (необработанное → чистый 500 без утечки трейсбэка).
    "EXCEPTION_HANDLER": "core.api.exceptions.custom_exception_handler",
    # Ограничение частоты запросов к публичному API (защита от злоупотреблений/скрейпинга).
    # Лимиты вынесены в окружение — в проде подстраиваются без правки кода.
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", default="120/min"),
        "user": env("THROTTLE_USER", default="600/min"),
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "RegionLens API",
    "DESCRIPTION": (
        "Программный доступ к социально-экономическим индикаторам регионов России и к "
        "аналитике RegionLens (композитный индекс развития, типология, аномалии, сценарии).\n\n"
        "**Данные** основаны на открытой статистике Росстата — чтение доступно без авторизации.\n\n"
        "**Аутентификация.** Персональный токен (личный кабинет → «API-доступ») передаётся "
        "заголовком `Authorization: Token <ключ>`. Токен идентифицирует запросы и повышает "
        "лимит частоты.\n\n"
        "**Ограничение частоты.** Без токена — 120 запросов/мин, с токеном — 600/мин. "
        "При превышении возвращается ответ `429 Too Many Requests`.\n\n"
        "**Версионирование.** Канонический префикс — `/api/v1/`. Неверсионированный `/api/` "
        "сохранён для обратной совместимости."
    ),
    "VERSION": "1.0.0",
    "CONTACT": {"name": "RegionLens", "url": "https://github.com/ht2473/RegionLens"},
    "LICENSE": {"name": "MIT"},
    "SERVE_INCLUDE_SCHEMA": False,
    "TAGS": [
        {"name": "Регионы", "description": "Справочник регионов и профили."},
        {
            "name": "Индекс",
            "description": "Композитный индекс развития, устойчивость, конвергенция.",
        },
        {"name": "Типология", "description": "Кластеризация регионов и профили типов."},
        {"name": "Показатели", "description": "Каталог метрик и временные ряды."},
        {"name": "Аналитика", "description": "Аномалии, корреляции, декомпозиция, сценарии."},
    ],
    # В схему попадает только канонический /api/v1/ (алиас /api/ скрыт от документации).
    "PREPROCESSING_HOOKS": ["core.api.schema.filter_versioned_paths"],
}

# Кэш: locmem по умолчанию (Redis — опционально в проде).
# Кэш: Redis в проде (общий для всех воркеров), локальный кэш в памяти по умолчанию.
REDIS_URL = env("REDIS_URL", default="")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "regionlens-locmem",
        }
    }

# Аутентификация (используется со страницами входа).
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# --- Безопасность боевого развёртывания ---------------------------------
# Принцип: локальная разработка идёт по HTTP (DEBUG=True), поэтому строгие флаги по
# умолчанию ВЫКЛЮЧЕНЫ и не мешают `runserver`. В боевом режиме (DJANGO_DEBUG=false)
# они автоматически ВКЛЮЧАЮТСЯ, давая чистый `manage.py check --deploy`. Каждый флаг
# дополнительно переопределяется собственной переменной окружения — тонкая настройка
# под конкретный хостинг. Это и есть «env-флаг прод-режима»: DEBUG управляет связкой.
_PROD = not DEBUG

# HTTPS: принудительный редирект + доверие заголовку X-Forwarded-Proto от
# TLS-терминирующего прокси/балансировщика (типовая схема PaaS). Если прокси нет —
# выключите DJANGO_TRUST_PROXY_SSL, иначе возможен цикл редиректов.
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=_PROD)
if env.bool("DJANGO_TRUST_PROXY_SSL", default=_PROD):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Cookies сессии и CSRF передаются только по HTTPS в проде.
SESSION_COOKIE_SECURE = env.bool("DJANGO_SESSION_COOKIE_SECURE", default=_PROD)
CSRF_COOKIE_SECURE = env.bool("DJANGO_CSRF_COOKIE_SECURE", default=_PROD)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# Доверенные источники для проверки Origin/Referer в POST-запросах. За HTTPS-прокси на
# собственном домене Django 5 требует явно указать источник со схемой (например,
# https://regionlens.example.com), иначе все формы (вход, смена языка, избранное) падают
# с ошибкой CSRF (403). Задаётся списком через окружение; в dev может быть пустым.
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# HSTS: год, с поддоменами и preload (в проде; в dev — 0, чтобы не «залипать» на HTTPS).
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=31_536_000 if _PROD else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=_PROD)
SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=_PROD)

# Анти-MIME-sniffing и анти-кликджекинг — включены всегда (dev не мешают).
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Предохранитель: в боевом режиме небезопасный дефолтный ключ недопустим.
if _PROD and SECRET_KEY == "dev-insecure-change-me":
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "В боевом режиме (DJANGO_DEBUG=false) необходимо задать длинный случайный "
        "DJANGO_SECRET_KEY в окружении (.env / переменные хостинга)."
    )
