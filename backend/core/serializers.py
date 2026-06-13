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


class GeoLayerPointSerializer(serializers.Serializer):
    """Точка слоя карты (надмножество полей measure=cluster|index — для OpenAPI-схемы)."""

    okato = serializers.CharField()
    cluster_id = serializers.IntegerField(required=False)
    cluster_label = serializers.CharField(required=False, allow_null=True)
    distance_to_centroid = serializers.FloatField(required=False, allow_null=True)
    total_score = serializers.FloatField(required=False, allow_null=True)


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


class IndexRowSerializer(serializers.Serializer):
    """Строка рейтинга регионов на год: ранг, итоговый балл и доменные баллы."""

    rank = serializers.IntegerField()
    okato = serializers.CharField()
    total_score = serializers.FloatField(allow_null=True)
    economy = serializers.FloatField(allow_null=True)
    income = serializers.FloatField(allow_null=True)
    demography = serializers.FloatField(allow_null=True)
    labor = serializers.FloatField(allow_null=True)
    infrastructure = serializers.FloatField(allow_null=True)
    health_edu = serializers.FloatField(allow_null=True)


class TransitionSerializer(serializers.Serializer):
    """Переход региона между типами год-к-году + тип его траектории."""

    okato = serializers.CharField()
    year_from = serializers.IntegerField()
    year_to = serializers.IntegerField()
    cluster_from = serializers.IntegerField(allow_null=True)
    cluster_to = serializers.IntegerField(allow_null=True)
    trajectory_type = serializers.CharField(allow_null=True)


# --- Дашборд региона (вложенная структура) ------------------------------------ #
class DomainDeltaSerializer(serializers.Serializer):
    """Доменный балл в году, в предыдущем году и дельта (B4 — арифметика по доменам)."""

    domain = serializers.CharField()
    score = serializers.FloatField(allow_null=True)
    score_prev = serializers.FloatField(allow_null=True)
    delta = serializers.FloatField(allow_null=True)


class IndexBlockSerializer(serializers.Serializer):
    """Блок индекса дашборда: итог, его дельта и поддоменная разбивка."""

    total_score = serializers.FloatField(allow_null=True)
    total_score_prev = serializers.FloatField(allow_null=True)
    total_delta = serializers.FloatField(allow_null=True)
    domains = DomainDeltaSerializer(many=True)


class ClusterBlockSerializer(serializers.Serializer):
    """Блок типологии дашборда: тип, метка, типичность (A1), стабильность."""

    cluster_id = serializers.IntegerField()
    cluster_label = serializers.CharField(allow_null=True)
    distance_to_centroid = serializers.FloatField(allow_null=True)
    stability_flag = serializers.FloatField(allow_null=True)


class ShapTopSerializer(serializers.Serializer):
    """Вклад метрики в принадлежность региона к типу (SHAP — объяснение, не причинность)."""

    metric_id = serializers.IntegerField()
    metric_name = serializers.CharField(allow_null=True)
    shap_value = serializers.FloatField()


class RankSerializer(serializers.Serializer):
    """Ранг региона по индексу среди всех регионов года."""

    rank = serializers.IntegerField()
    of = serializers.IntegerField()


class RegionDashboardSerializer(serializers.Serializer):
    """Полный дашборд региона на год (центральный экран региона)."""

    okato = serializers.CharField()
    year = serializers.IntegerField()
    region_name = serializers.CharField(allow_null=True)
    federal_district = serializers.CharField(allow_null=True)
    index = IndexBlockSerializer()
    cluster = ClusterBlockSerializer(allow_null=True)
    shap_top = ShapTopSerializer(many=True)
    rank = RankSerializer(allow_null=True)


class TypologyRowSerializer(serializers.Serializer):
    """Принадлежность региона к типу на год (для обзора типологии и карты)."""

    okato = serializers.CharField()
    cluster_id = serializers.IntegerField()
    cluster_label = serializers.CharField(allow_null=True)
    distance_to_centroid = serializers.FloatField(allow_null=True)
    stability_flag = serializers.FloatField(allow_null=True)


class TypologyExplainSerializer(serializers.Serializer):
    """SHAP-объяснение принадлежности региона к типу (полный список по |вкладу|)."""

    okato = serializers.CharField()
    year = serializers.IntegerField()
    cluster_id = serializers.IntegerField()
    cluster_label = serializers.CharField(allow_null=True)
    shap = ShapTopSerializer(many=True)


class ClusterProfileRowSerializer(serializers.Serializer):
    """Строка профиля типа: средний z метрики (чем характерен тип)."""

    metric_id = serializers.IntegerField()
    metric_name = serializers.CharField(allow_null=True)
    mean_z = serializers.FloatField(allow_null=True)


class CompareRowSerializer(serializers.Serializer):
    """Строка сравнения регионов: индекс по доменам + тип (для gap-анализа)."""

    okato = serializers.CharField()
    region_name = serializers.CharField(allow_null=True)
    total_score = serializers.FloatField(allow_null=True)
    economy = serializers.FloatField(allow_null=True)
    income = serializers.FloatField(allow_null=True)
    demography = serializers.FloatField(allow_null=True)
    labor = serializers.FloatField(allow_null=True)
    infrastructure = serializers.FloatField(allow_null=True)
    health_edu = serializers.FloatField(allow_null=True)
    cluster_id = serializers.IntegerField(allow_null=True)
    cluster_label = serializers.CharField(allow_null=True)


class RegionTwinSerializer(serializers.Serializer):
    """Статистический двойник региона: похожий по профилю z_value регион за год (C2).

    similarity — косинусная близость профилей показателей в этот год (∈[−1;1]); rank: 1 —
    самый похожий. Это сходство профиля показателей, НЕ причинность и НЕ прогноз.
    """

    rank = serializers.IntegerField()
    twin_okato = serializers.CharField()
    region_name = serializers.CharField(allow_null=True)
    federal_district = serializers.CharField(allow_null=True)
    similarity = serializers.FloatField()


class AnomalySerializer(serializers.Serializer):
    """Строка диагностики аномалий/сдвигов (Ф9). okato/region_name пусты для находок уровня
    «метрика-год» (methodology_change, A3); metric_id/metric_name пусты для пространственных
    выбросов. kind ∈ {spatial, structural_break, methodology_change}. score: для spatial —
    оценка типичности (меньше → аномальнее); для structural_break — величина сдвига; для
    methodology_change — доля синхронно затронутых регионов.
    """

    okato = serializers.CharField(allow_null=True)
    region_name = serializers.CharField(allow_null=True)
    metric_id = serializers.IntegerField(allow_null=True)
    metric_name = serializers.CharField(allow_null=True)
    year = serializers.IntegerField()
    score = serializers.FloatField()
    is_anomaly = serializers.BooleanField()
    kind = serializers.CharField()


class DispersionRowSerializer(serializers.Serializer):
    """Строка разброса/неравенства по регионам на (метрику, год) из таблицы dispersion.

    metric_name/domain могут быть пусты (LEFT JOIN). cv и p90_p10_ratio пусты для величин
    без шкалы отношений (index/rate_yoy) либо при неположительных mean/p10 — это ожидаемо.
    Прочие статистики (std, iqr, value_range) считаются всегда. Описательная мера.
    """

    metric_id = serializers.IntegerField()
    metric_name = serializers.CharField(allow_null=True)
    domain = serializers.CharField(allow_null=True)
    year = serializers.IntegerField()
    n_regions = serializers.IntegerField()
    mean = serializers.FloatField(allow_null=True)
    median = serializers.FloatField(allow_null=True)
    std = serializers.FloatField(allow_null=True)
    p10 = serializers.FloatField(allow_null=True)
    p90 = serializers.FloatField(allow_null=True)
    iqr = serializers.FloatField(allow_null=True)
    value_range = serializers.FloatField(allow_null=True)
    cv = serializers.FloatField(allow_null=True)
    p90_p10_ratio = serializers.FloatField(allow_null=True)
