"""DRF-сериализаторы ответов API (Ф6): фиксируют форму выдачи и питают OpenAPI-схему.

Данные приходят из core.queries уже готовыми словарями (из DuckDB); сериализаторы
здесь — это контракт формы ответа (Хартия §2: контракты раньше кода) и источник
схемы для drf-spectacular. Поля nullable там, где значение может отсутствовать
(направление метрики задано только у ядра; гармонизированное значение — после Ф2).
"""

from __future__ import annotations

from rest_framework import serializers


class RegionSerializer(serializers.Serializer):
    """Элемент каталога регионов (из region_dim, только участвующие в аналитике)."""

    okato = serializers.CharField()
    region_name = serializers.CharField()
    federal_district = serializers.CharField(allow_null=True)


class MetricSerializer(serializers.Serializer):
    """Элемент каталога метрик ядра (из metric_dim)."""

    metric_id = serializers.IntegerField()
    metric_name = serializers.CharField()
    domain = serializers.CharField(allow_null=True)
    unit = serializers.CharField(allow_null=True)
    value_type = serializers.CharField(allow_null=True)
    higher_is_better = serializers.BooleanField(allow_null=True)
    coverage = serializers.FloatField(allow_null=True)


class MetricSeriesPointSerializer(serializers.Serializer):
    """Точка временного ряда метрики по региону (из fact_region; полный диапазон годов)."""

    year = serializers.IntegerField()
    value = serializers.FloatField(allow_null=True)
    value_harmonized = serializers.FloatField(allow_null=True)
    is_imputed = serializers.BooleanField(allow_null=True)
