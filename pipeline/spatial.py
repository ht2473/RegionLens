"""Пространственная автокорреляция индекса развития: глобальный Moran's I и локальный LISA.

Проверяем, кластеризуются ли соседние регионы по индексу развития. Пространственные веса
(соседство) строим из границ субъектов: два региона смежны, если их полигоны делят общее ребро
(≥2 общие вершины упрощённого geojson — rook-смежность). Глобальный Moran's I со значимостью через
перестановочный тест; локальный LISA относит каждый регион к квадранту HH/LL/HL/LH с перестановочной
p-значимостью. Считается по каждой паре (год, схема весов) поверх готового dev_index.

Статистику считает esda (PySAL) — стандартная библиотека пространственной эконометрики; веса строит
libpysal.weights.W из словаря соседства (геометрия не нужна). Это описательная статистика над уже
посчитанными баллами (не модель и не прогноз). Детерминизм: seed=42.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import esda
import libpysal
import numpy as np
import polars as pl

from pipeline.contracts import MORAN_GLOBAL_SCHEMA, MORAN_LOCAL_SCHEMA
from pipeline.duck import read_table, write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"
DEFAULT_GEOJSON_PATH = "backend/static/geo/regions.geojson"
SEED = 42
PERMUTATIONS = 999
SIGNIFICANCE = 0.05
MIN_SHARED_VERTICES = 2  # общее ребро (rook), а не касание углом
# Метки квадрантов LISA по коду esda .q: 1=HH, 2=LH, 3=LL, 4=HL.
_QUADRANT = {1: "HH", 2: "LH", 3: "LL", 4: "HL"}


def _feature_vertices(geometry: dict[str, Any]) -> set[tuple[float, float]]:
    """Множество вершин геометрии (округлённых), для поиска общих границ."""
    verts: set[tuple[float, float]] = set()

    def walk(node: Any) -> None:
        if isinstance(node, (list, tuple)):
            if node and isinstance(node[0], (int, float)):
                verts.add((round(float(node[0]), 6), round(float(node[1]), 6)))
            else:
                for child in node:
                    walk(child)

    walk(geometry.get("coordinates"))
    return verts


def build_adjacency(geojson_path: str = DEFAULT_GEOJSON_PATH) -> dict[str, list[str]]:
    """Соседство субъектов по общей границе (rook) из geojson: okato → список соседних okato.

    Топологически упрощённый geojson делит между соседями идентичные вершины, поэтому смежность
    ловим по общим вершинам: регионы смежны, если делят ≥2 вершины (общее ребро). Эксклавы и
    острова (Калининград, Сахалин и т. п.) соседей не имеют — у них пустой список.
    """
    fc = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
    owners: dict[tuple[float, float], set[str]] = defaultdict(set)
    all_okato: list[str] = []
    for feat in fc["features"]:
        okato = feat["properties"]["okato"]
        all_okato.append(okato)
        for v in _feature_vertices(feat["geometry"]):
            owners[v].add(okato)

    shared: dict[tuple[str, str], int] = defaultdict(int)
    for region_set in owners.values():
        if len(region_set) >= 2:
            for a, b in combinations(sorted(region_set), 2):
                shared[(a, b)] += 1

    neighbors: dict[str, list[str]] = {okato: [] for okato in all_okato}
    for (a, b), count in shared.items():
        if count >= MIN_SHARED_VERTICES:
            neighbors[a].append(b)
            neighbors[b].append(a)
    return neighbors


@dataclass
class SpatialResult:
    moran_global: pl.DataFrame
    moran_local: pl.DataFrame


def _moran_for_slice(
    scores: dict[str, float], neighbors: dict[str, list[str]]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Moran's I (глобальный + LISA) для одного среза (год, схема). Регионы без соседей — ns."""
    present = set(scores)
    # соседство внутри среза; связные регионы — те, у кого остались соседи
    sub = {ok: [n for n in neighbors.get(ok, []) if n in present] for ok in present}
    connected = [ok for ok in sub if sub[ok]]

    local_rows: list[dict[str, Any]] = []
    # эксклавы/острова: в статистику не входят, но строку LISA отдаём как ns
    for ok in present:
        if not sub[ok]:
            local_rows.append(
                {"okato": ok, "local_i": None, "quadrant": "ns", "p_value": None, "n_neighbors": 0}
            )

    if len(connected) < 3:
        return None, local_rows

    w = libpysal.weights.W({ok: sub[ok] for ok in connected}, silence_warnings=True)
    w.transform = "r"
    order = list(w.id_order)
    y = np.array([scores[ok] for ok in order], dtype=float)

    np.random.seed(SEED)
    mg = esda.Moran(y, w, permutations=PERMUTATIONS)
    # alternative='two-sided' — рекомендованный esda режим значимости LISA (двусторонний,
    # консервативнее и стабилен между версиями библиотеки).
    ml = esda.Moran_Local(y, w, permutations=PERMUTATIONS, seed=SEED, alternative="two-sided")

    global_row = {
        "morans_i": float(mg.I),
        "expected_i": float(mg.EI),
        "z_score": float(mg.z_sim),
        "p_value": float(mg.p_sim),
        "n_regions": int(len(order)),
    }
    for i, ok in enumerate(order):
        p = float(ml.p_sim[i])
        significant = p < SIGNIFICANCE
        local_rows.append(
            {
                "okato": ok,
                "local_i": float(ml.Is[i]),
                "quadrant": _QUADRANT.get(int(ml.q[i]), "ns") if significant else "ns",
                "p_value": p,
                "n_neighbors": len(sub[ok]),
            }
        )
    return global_row, local_rows


def compute_moran(
    dev_index: pl.DataFrame, neighbors: dict[str, list[str]]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Глобальный Moran's I и локальный LISA по каждой (year, weighting_scheme) поверх dev_index."""
    global_rows: list[dict[str, Any]] = []
    local_rows: list[dict[str, Any]] = []
    keys = dev_index.select("weighting_scheme", "year").unique().sort(["weighting_scheme", "year"])
    for key in keys.iter_rows(named=True):
        scheme, year = key["weighting_scheme"], key["year"]
        sub = dev_index.filter(
            (pl.col("weighting_scheme") == scheme) & (pl.col("year") == year)
        ).select("okato", "total_score")
        scores = {
            r["okato"]: float(r["total_score"])
            for r in sub.iter_rows(named=True)
            if r["total_score"] is not None
        }
        g, locals_ = _moran_for_slice(scores, neighbors)
        if g is not None:
            global_rows.append({"weighting_scheme": scheme, "year": year, **g})
        for lr in locals_:
            local_rows.append({"weighting_scheme": scheme, "year": year, **lr})

    global_df = pl.DataFrame(global_rows, schema=MORAN_GLOBAL_SCHEMA)
    local_df = pl.DataFrame(local_rows, schema=MORAN_LOCAL_SCHEMA)
    return global_df, local_df


def run_spatial(
    dev_index: pl.DataFrame,
    *,
    geojson_path: str = DEFAULT_GEOJSON_PATH,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> SpatialResult:
    """Посчитать Moran's I/LISA и (при write=True) записать moran_global/moran_local в DuckDB."""
    neighbors = build_adjacency(geojson_path)
    degrees = [len(v) for v in neighbors.values()]
    isolates = sum(1 for d in degrees if d == 0)
    global_df, local_df = compute_moran(dev_index, neighbors)
    log.info(
        "spatial_built",
        stage="spatial",
        regions=len(neighbors),
        isolates=isolates,
        avg_degree=round(sum(degrees) / len(degrees), 2) if degrees else 0,
        global_rows=global_df.height,
        local_rows=local_df.height,
    )
    if write:
        write_table(duckdb_path, "moran_global", global_df)
        write_table(duckdb_path, "moran_local", local_df)
    return SpatialResult(moran_global=global_df, moran_local=local_df)


if __name__ == "__main__":
    dev = read_table(DEFAULT_DUCKDB_PATH, "dev_index")
    run_spatial(dev)
