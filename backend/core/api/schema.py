"""Хуки drf-spectacular для схемы OpenAPI.

API смонтирован под двумя префиксами: канонический `/api/v1/` и алиас `/api/` (обратная
совместимость). В схему должен попадать только версионированный префикс — иначе каждый
эндпойнт задваивается. `filter_versioned_paths` отбрасывает неверсионированный алиас.
"""

from __future__ import annotations

from typing import Any

_CANONICAL_PREFIX = "/api/v1/"


def filter_versioned_paths(
    endpoints: list[tuple[Any, ...]], **kwargs: Any
) -> list[tuple[Any, ...]]:
    """Оставить в схеме только пути канонического префикса `/api/v1/`.

    drf-spectacular передаёт список кортежей (path, path_regex, method, callback); возвращаем
    подмножество с версионированными путями, скрывая дубли из алиаса `/api/`.
    """
    return [ep for ep in endpoints if ep[0].startswith(_CANONICAL_PREFIX)]
