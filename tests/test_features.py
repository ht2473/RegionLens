"""Тесты признаков (Ф2 / S3, блок A): value_type, покрытие, обогащение, гармонизация."""

from __future__ import annotations

import polars as pl

from pipeline.features import (
    classify_value_type,
    compute_coverage,
    enrich_metric_dim,
    harmonize,
    select_core,
)

# Правила в том же порядке, что и в config/value_types.yaml (важно: rate_yoy раньше share).
_RULES = [
    {"match": "к предыдущему году", "type": "rate_yoy"},
    {"match": "в процентах", "type": "share"},
    {"match": "на душу", "type": "per_capita"},
]
_VT = (_RULES, "absolute", "ND")


def test_classify_value_type_order_and_default() -> None:
    """rate_yoy ловится раньше share; на душу -> per_capita; иначе default; ND -> default."""
    assert classify_value_type("В процентах к предыдущему году", *_VT) == "rate_yoy"
    assert classify_value_type("В процентах от общего объема", *_VT) == "share"
    assert classify_value_type("Рублей на душу населения", *_VT) == "per_capita"
    assert classify_value_type("Миллионов рублей", *_VT) == "absolute"
    assert classify_value_type("ND", *_VT) == "absolute"
    assert classify_value_type(None, *_VT) == "absolute"


def _region_dim() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "okato": ["01", "02", "03"],
            "included_flag": [True, True, False],  # 03 — исключённый вариант «с/без АО»
        }
    )


def test_compute_coverage_uses_included_and_window() -> None:
    """Знаменатель = включённые регионы × окно; считаются только непустые значения."""
    # окно [2010, 2011]; включены 01 и 02 -> denom = 2*2 = 4.
    fact = pl.DataFrame(
        {
            "okato": ["01", "01", "02", "03", "01"],
            "metric_id": [1, 1, 1, 1, 1],
            "year": [2010, 2011, 2010, 2010, 2009],  # 2009 вне окна, 03 исключён
            "value": [10.0, 20.0, 30.0, 99.0, 5.0],
        }
    )
    cov = compute_coverage(fact, _region_dim(), [2010, 2011])
    # заполнено 3 ячейки (01/2010, 01/2011, 02/2010) из 4 -> 0.75
    assert abs(cov.filter(pl.col("metric_id") == 1)["coverage"][0] - 0.75) < 1e-9


def _metric_dim() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "metric_id": [1, 2, 1781],
            "indicator_code": ["A", "B", "P"],
            "subsection": ["x", "y", "z"],
            "metric_name": ["доходы", "оборот", "население"],
            "unit": ["Рублей в месяц", "Миллионов рублей", "Оценка, тысяч человек"],
            "section": ["Уровень жизни населения", "Организации", "Население"],
        }
    )


def _indicators_cfg() -> dict[str, object]:
    return {
        "population_metric_id": 1781,
        "default_domain": "excluded",
        "domains": {"Организации": "economy", "Население": "demography"},
        "core": [
            {
                "metric_id": 1,
                "name": "доходы",
                "domain": "income",
                "value_type": "per_capita",
                "higher_is_better": True,
            },
            {
                "metric_id": 2,
                "name": "оборот",
                "domain": "economy",
                "value_type": "absolute",
                "higher_is_better": True,
            },
        ],
    }


def test_enrich_metric_dim_core_overrides_tail() -> None:
    """Ядро берёт domain/value_type/higher_is_better из конфига; хвост — по карте/правилам."""
    cov = pl.DataFrame({"metric_id": [1, 2], "coverage": [0.97, 0.95]})
    md = enrich_metric_dim(_metric_dim(), _indicators_cfg(), _VT, cov)
    rows = {int(r["metric_id"]): r for r in md.to_dicts()}
    assert rows[1]["domain"] == "income" and rows[1]["value_type"] == "per_capita"
    assert rows[1]["higher_is_better"] is True
    assert rows[2]["domain"] == "economy" and rows[2]["value_type"] == "absolute"
    # 1781 не в ядре: домен по карте section->демография, направление неизвестно
    assert rows[1781]["domain"] == "demography"
    assert rows[1781]["higher_is_better"] is None
    assert rows[1781]["coverage"] == 0.0  # не было в coverage -> заполнено нулём


def test_harmonize_divides_only_absolute() -> None:
    """absolute делится на население; per_capita проходит без изменений; нет населения -> null."""
    md = pl.DataFrame({"metric_id": [1, 2], "value_type": ["per_capita", "absolute"]})
    fact = pl.DataFrame(
        {
            "okato": ["01", "01", "01"],
            "metric_id": [1, 2, 1781],
            "year": [2010, 2010, 2010],
            "value": [25000.0, 1000.0, 500.0],  # население = 500 (тыс)
        }
    )
    out = harmonize(fact, md, pop_id=1781).sort("metric_id")
    by = {int(r["metric_id"]): r["value_harmonized"] for r in out.to_dicts()}
    assert by[1] == 25000.0  # per_capita без деления
    assert by[2] == 2.0  # 1000 / 500


def test_select_core_warns_below_threshold() -> None:
    """Возвращает все metric_id ядра; просадку по покрытию только логирует, не отсеивает."""
    md = pl.DataFrame({"metric_id": [1, 2], "coverage": [0.97, 0.40]})
    core_ids = select_core(md, _indicators_cfg(), coverage_threshold=0.80)
    assert core_ids == [1, 2]
