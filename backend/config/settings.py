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
ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0"]
)

# OLTP: PostgreSQL через DATABASE_URL. По умолчанию — локальный sqlite-fallback, чтобы
# tooling и первый запуск работали без поднятого Postgres. Прод/dev используют Postgres.
_default_db = "sqlite:///" + str(REPO_ROOT / "db.sqlite3")
DATABASES = {"default": env.db("DATABASE_URL", default=_default_db)}

# OLAP: путь к DuckDB-файлу (read-only из приложения; владелец — конвейер).
DUCKDB_PATH = env("DUCKDB_PATH", default=str(REPO_ROOT / "data" / "regionlens.duckdb"))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = REPO_ROOT / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = REPO_ROOT / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DRF: сессионная аутентификация (не JWT) + схема drf-spectacular.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "RegionLens API",
    "DESCRIPTION": "Аналитические и операционные эндпойнты RegionLens.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# Кэш: locmem по умолчанию (Redis — опционально в проде; см. Ф12/Could).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "regionlens-locmem",
    }
}

# Аутентификация (используется со страницами входа в Ф10).
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
