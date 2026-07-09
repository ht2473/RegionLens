"""Версионирование API: канонический /api/v1/ + алиас /api/ и чистая схема OpenAPI."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import resolve, reverse

pytestmark = pytest.mark.django_db


def test_v1_and_alias_map_to_same_view() -> None:
    """И /api/v1/regions/, и /api/regions/ ведут в одно и то же представление."""
    assert resolve("/api/v1/regions/").func.__name__ == resolve("/api/regions/").func.__name__


def test_canonical_reverse_is_versioned() -> None:
    """Пространство имён `api` указывает на канонический версионированный префикс."""
    assert reverse("api:regions") == "/api/v1/regions/"
    assert reverse("api:schema") == "/api/v1/schema/"
    assert reverse("api:swagger-ui") == "/api/v1/docs/"


def test_alias_reverse_is_unversioned() -> None:
    """Алиас совместимости доступен под /api/ через пространство имён `api-compat`."""
    assert reverse("api-compat:regions") == "/api/regions/"


def test_schema_documents_token_authentication() -> None:
    """OpenAPI описывает способ аутентификации по токену (иначе spectacular предупреждает)."""
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    schemes = schema.get("components", {}).get("securitySchemes", {})
    assert "ApiTokenAuth" in schemes
    assert schemes["ApiTokenAuth"]["type"] == "apiKey"
    assert schemes["ApiTokenAuth"]["in"] == "header"


def test_schema_only_contains_versioned_paths() -> None:
    """Хук препроцессинга оставляет в схеме только /api/v1/ (без дублей алиаса)."""
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    paths = list(schema["paths"])
    assert paths, "схема не должна быть пустой"
    assert all(p.startswith("/api/v1/") for p in paths)
    assert schema["info"]["version"] == "1.0.0"


def test_schema_endpoint_served_under_v1() -> None:
    """Эндпойнт схемы отдаётся по версионированному пути и содержит версионированные пути."""
    resp = Client().get("/api/v1/schema/")
    assert resp.status_code == 200
    assert "/api/v1/regions/" in resp.content.decode()
