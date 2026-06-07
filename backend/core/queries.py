"""Параметризованные read-only запросы к контрактным таблицам DuckDB (Ф6).

Единственная точка обращения приложения к аналитическому хранилищу. Изоляция SQL
делает хранилище заменяемым (Хартия §8, swappable storage): при переезде на
ClickHouse/Postgres меняется только этот модуль — API и фронт остаются нетронутыми.
Константы слоёв карты (алгоритм типологии, схема весов индекса) — здесь, т.к. это
«какой слой показываем», а не параметр запроса пользователя.
"""

from __future__ import annotations

from typing import Any

from .duck import q

# Канонические слои карты: типология строится KMeans, базовый индекс — равные веса.
MAP_CLUSTER_ALGO = "kmeans"
MAP_INDEX_SCHEME = "equal"


def geo_layer(year: int, measure: str) -> list[dict[str, Any]]:
    """Слой карты на год: значения по регионам для раскраски (стыковка по okato).

    measure='cluster' → тип региона (cluster_id), осмысленная метка и
    distance_to_centroid (A1: градиент типичности/пограничности — насколько регион
    типичен для своего типа, НЕ вероятность перехода).
    measure='index'   → итоговый индекс развития total_score [0;100].
    """
    if measure == "cluster":
        return q(
            "SELECT okato, cluster_id, cluster_label, distance_to_centroid "
            "FROM clusters WHERE year = ? AND algo = ? ORDER BY okato",
            [year, MAP_CLUSTER_ALGO],
        )
    return q(
        "SELECT okato, total_score "
        "FROM dev_index WHERE year = ? AND weighting_scheme = ? ORDER BY okato",
        [year, MAP_INDEX_SCHEME],
    )


def regions() -> list[dict[str, Any]]:
    """Каталог регионов, участвующих в аналитике (included_flag), для списков/выпадашек.

    Варианты-агрегаты «с/без АО» отфильтрованы (included_flag=false) — остаются только
    85 непересекающихся субъектов. Сортировка по имени — для удобного отображения.
    """
    return q(
        "SELECT okato, region_name, federal_district "
        "FROM region_dim WHERE included_flag = TRUE ORDER BY region_name"
    )


def metrics(domain: str | None = None) -> list[dict[str, Any]]:
    """Каталог метрик ядра (опц. фильтр по домену).

    Ядро отличается от «хвоста» тем, что у него задано направление (higher_is_better
    проставлен только для курируемого ядра в Ф2) — это и используем как дискриминатор.
    """
    sql = (
        "SELECT metric_id, metric_name, domain, unit, value_type, higher_is_better, coverage "
        "FROM metric_dim WHERE higher_is_better IS NOT NULL"
    )
    params: list[Any] = []
    if domain:
        sql += " AND domain = ?"
        params.append(domain)
    sql += " ORDER BY domain, metric_name"
    return q(sql, params)


def metric_series(
    metric_id: int, okato: str, year_from: int | None = None, year_to: int | None = None
) -> list[dict[str, Any]]:
    """Временной ряд метрики по региону из fact_region (полный диапазон годов).

    Полный диапазон (а не окно 2010–2024) — потому что для отображения рядов на
    дашбордах допустимы все годы; окно ограничивает только расчёт аналитики (Хартия §3).
    Параметры from/to — необязательные границы по году. Значения параметризованы (?).
    """
    sql = (
        "SELECT year, value, value_harmonized, is_imputed "
        "FROM fact_region WHERE metric_id = ? AND okato = ?"
    )
    params: list[Any] = [metric_id, okato]
    if year_from is not None:
        sql += " AND year >= ?"
        params.append(year_from)
    if year_to is not None:
        sql += " AND year <= ?"
        params.append(year_to)
    sql += " ORDER BY year"
    return q(sql, params)


# Домены индекса (порядок фиксирован, как в pipeline.dev_index.DOMAIN_COLS).
INDEX_DOMAINS = ["economy", "income", "demography", "labor", "infrastructure", "health_edu"]
SHAP_TOP_N = 8  # сколько метрик показывать в SHAP-объяснении принадлежности


def index_ranking(year: int, scheme: str = MAP_INDEX_SCHEME) -> list[dict[str, Any]]:
    """Рейтинг регионов на год по total_score (по убыванию) с проставленным rank.

    Возвращает total_score и доменные баллы — питает экран рейтингов и вычисление
    ранга в дашборде региона.
    """
    cols = "okato, total_score, " + ", ".join(INDEX_DOMAINS)
    rows = q(
        f"SELECT {cols} FROM dev_index "
        "WHERE year = ? AND weighting_scheme = ? ORDER BY total_score DESC",
        [year, scheme],
    )
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows


def _domain_breakdown(cur: dict[str, Any], prev: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Поддоменная разбивка балла: значение в году, в предыдущем году и дельта (B4).

    Это арифметическая разбивка балла ПО ДОМЕНАМ (не причинность). Доменные баллы НЕ
    суммируются в total_score (тот считается по весам схемы и нормируется в [0;100]),
    поэтому total в дашборде показывается отдельным блоком.
    """
    out: list[dict[str, Any]] = []
    for d in INDEX_DOMAINS:
        score = cur.get(d)
        score_prev = prev.get(d) if prev else None
        delta = score - score_prev if score is not None and score_prev is not None else None
        out.append({"domain": d, "score": score, "score_prev": score_prev, "delta": delta})
    return out


def region_dashboard(
    okato: str, year: int, scheme: str = MAP_INDEX_SCHEME
) -> dict[str, Any] | None:
    """Дашборд региона на год: индекс по доменам (+B4-дельта), кластер, SHAP-топ, ранг.

    Возвращает None, если для (okato, year, scheme) нет записи индекса (→ 404 в API).
    """
    cols = "total_score, " + ", ".join(INDEX_DOMAINS)
    cur_rows = q(
        f"SELECT {cols} FROM dev_index WHERE okato = ? AND year = ? AND weighting_scheme = ?",
        [okato, year, scheme],
    )
    if not cur_rows:
        return None
    cur = cur_rows[0]
    prev_rows = q(
        f"SELECT {cols} FROM dev_index WHERE okato = ? AND year = ? AND weighting_scheme = ?",
        [okato, year - 1, scheme],
    )
    prev = prev_rows[0] if prev_rows else None
    total = cur["total_score"]
    total_prev = prev["total_score"] if prev else None
    total_delta = total - total_prev if total_prev is not None else None

    reg_rows = q("SELECT region_name, federal_district FROM region_dim WHERE okato = ?", [okato])
    reg = reg_rows[0] if reg_rows else {"region_name": None, "federal_district": None}

    clus_rows = q(
        "SELECT cluster_id, cluster_label, distance_to_centroid, stability_flag "
        "FROM clusters WHERE okato = ? AND year = ? AND algo = ?",
        [okato, year, MAP_CLUSTER_ALGO],
    )
    cluster = clus_rows[0] if clus_rows else None

    shap_top = q(
        "SELECT s.metric_id, m.metric_name, s.shap_value "
        "FROM cluster_shap s JOIN metric_dim m USING(metric_id) "
        "WHERE s.okato = ? AND s.year = ? ORDER BY abs(s.shap_value) DESC LIMIT ?",
        [okato, year, SHAP_TOP_N],
    )

    ranking = index_ranking(year, scheme)
    rank = next((r["rank"] for r in ranking if r["okato"] == okato), None)

    return {
        "okato": okato,
        "year": year,
        "region_name": reg["region_name"],
        "federal_district": reg["federal_district"],
        "index": {
            "total_score": total,
            "total_score_prev": total_prev,
            "total_delta": total_delta,
            "domains": _domain_breakdown(cur, prev),
        },
        "cluster": cluster,
        "shap_top": shap_top,
        "rank": {"rank": rank, "of": len(ranking)} if rank is not None else None,
    }


def transitions_list(okato: str | None = None) -> list[dict[str, Any]]:
    """Переходы между типами + тип траектории. С okato — путь региона; без — все потоки."""
    cols = "okato, year_from, year_to, cluster_from, cluster_to, trajectory_type"
    if okato:
        return q(
            f"SELECT {cols} FROM transitions WHERE okato = ? ORDER BY year_from",
            [okato],
        )
    return q(f"SELECT {cols} FROM transitions ORDER BY okato, year_from")


def typology(year: int, k: int | None = None) -> list[dict[str, Any]]:
    """Типология на год: тип/метка/типичность(A1)/стабильность по каждому региону."""
    sql = (
        "SELECT okato, cluster_id, cluster_label, distance_to_centroid, stability_flag "
        "FROM clusters WHERE year = ? AND algo = ?"
    )
    params: list[Any] = [year, MAP_CLUSTER_ALGO]
    if k is not None:
        sql += " AND k = ?"
        params.append(k)
    sql += " ORDER BY okato"
    return q(sql, params)


def typology_explain(okato: str, year: int) -> dict[str, Any] | None:
    """SHAP-объяснение принадлежности региона к типу за год (все метрики по |вкладу|).

    SHAP объясняет решение классификатора (почему регион отнесён к типу), это НЕ
    причинность. Возвращает None, если региона нет в типологии за год (→ 404 в API).
    """
    clus = q(
        "SELECT cluster_id, cluster_label FROM clusters WHERE okato = ? AND year = ? AND algo = ?",
        [okato, year, MAP_CLUSTER_ALGO],
    )
    if not clus:
        return None
    shap = q(
        "SELECT s.metric_id, m.metric_name, s.shap_value "
        "FROM cluster_shap s JOIN metric_dim m USING(metric_id) "
        "WHERE s.okato = ? AND s.year = ? ORDER BY abs(s.shap_value) DESC",
        [okato, year],
    )
    return {
        "okato": okato,
        "year": year,
        "cluster_id": clus[0]["cluster_id"],
        "cluster_label": clus[0]["cluster_label"],
        "shap": shap,
    }


def cluster_profile(year: int, cluster_id: int, k: int | None = None) -> list[dict[str, Any]]:
    """Профиль типа за год: средний z метрик (по |mean_z|) — чем характерен тип."""
    sql = (
        "SELECT p.metric_id, m.metric_name, p.mean_z "
        "FROM cluster_profile p JOIN metric_dim m USING(metric_id) "
        "WHERE p.year = ? AND p.cluster_id = ? AND p.algo = ?"
    )
    params: list[Any] = [year, cluster_id, MAP_CLUSTER_ALGO]
    if k is not None:
        sql += " AND p.k = ?"
        params.append(k)
    sql += " ORDER BY abs(p.mean_z) DESC"
    return q(sql, params)


def compare(okatos: list[str], year: int, scheme: str = MAP_INDEX_SCHEME) -> list[dict[str, Any]]:
    """Сравнение регионов на год: индекс по доменам + тип — для gap-анализа на фронте."""
    placeholders = ", ".join(["?"] * len(okatos))
    cols = "d.okato, r.region_name, d.total_score, " + ", ".join(f"d.{c}" for c in INDEX_DOMAINS)
    rows = q(
        f"SELECT {cols} FROM dev_index d JOIN region_dim r USING(okato) "
        f"WHERE d.year = ? AND d.weighting_scheme = ? AND d.okato IN ({placeholders}) "
        "ORDER BY d.total_score DESC",
        [year, scheme, *okatos],
    )
    clus = q(
        f"SELECT okato, cluster_id, cluster_label FROM clusters "
        f"WHERE year = ? AND algo = ? AND okato IN ({placeholders})",
        [year, MAP_CLUSTER_ALGO, *okatos],
    )
    clus_by = {c["okato"]: c for c in clus}
    for row in rows:
        c = clus_by.get(row["okato"])
        row["cluster_id"] = c["cluster_id"] if c else None
        row["cluster_label"] = c["cluster_label"] if c else None
    return rows
