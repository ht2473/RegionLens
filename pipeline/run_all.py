"""Оркестратор конвейера: единая воспроизводимая пересборка всей аналитики.

Запуск:
    python -m pipeline.run_all                  # весь конвейер: сырьё → DuckDB (S2 … C2)
    python -m pipeline.run_all --list           # показать план (стадии и их таблицы)
    python -m pipeline.run_all --from typology  # пересобрать с указанной стадии и до конца
    python -m pipeline.run_all --only twins      # пересобрать ровно одну стадию

Архитектура «двух миров» (Хартия §1): DuckDB-файл пишет ТОЛЬКО офлайн-конвейер, а
приложение открывает его строго read-only. Каждая стадия читает входные контрактные
таблицы из DuckDB (стадия ETL — из сырья) и записывает свои выходы туда же. Благодаря
этому `--from`/`--only` корректно возобновляют сборку с диска: всё, что произвели
предыдущие стадии, уже лежит в хранилище.

Прогнозирование (бывшая стадия S7) намеренно исключено из плана: платформа усиливается
описательно-диагностической аналитикой без предсказаний.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pipeline.duck import list_tables, read_table
from pipeline.logging_setup import configure_logging, log

#: Путь к аналитическому хранилищу по умолчанию (совпадает с DEFAULT_DUCKDB_PATH стадий).
DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"
#: Реестр источников для стадии ETL (без хардкода — берётся отсюда).
DEFAULT_SOURCES_PATH = "config/sources.yaml"


@dataclass(frozen=True)
class Stage:
    """Описание одной стадии конвейера.

    Поля:
        name: короткое имя стадии (используется в --only/--from и в логах);
        run: функция запуска (читает входы из DuckDB и пишет выходы туда же);
        reads: контрактные таблицы-входы (пустой кортеж — стадия читает сырьё);
        writes: контрактные таблицы-выходы (проверяются после запуска);
        description: однострочное пояснение для плана (--list).
    """

    name: str
    run: Callable[[str, str, bool], None]
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    description: str


# --- Стадии: тонкие обёртки над run_*-функциями модулей конвейера ---------------------
# Тяжёлые зависимости (sklearn/ruptures/shap/…) импортируются лениво внутри функций,
# поэтому сам импорт pipeline.run_all остаётся лёгким (нужно для --list и тестов плана).


def _stage_etl(duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
    """S2: источники → metric_id → уровни → дедуп → справочники → fact_region."""
    from pipeline.etl import run_etl

    run_etl(sources_path, duckdb_path, write=True)


def _stage_features(duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
    """Ф2: гармонизация форм, обогащение metric_dim, ядро, импутация, z-score."""
    from pipeline.features import run_features

    metric_dim = read_table(duckdb_path, "metric_dim")
    region_dim = read_table(duckdb_path, "region_dim")
    fact_region = read_table(duckdb_path, "fact_region")
    run_features(metric_dim, region_dim, fact_region, duckdb_path=duckdb_path, write=True)


def _stage_typology(duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
    """Ф3: кластеризация по годам со стабильными метками + SHAP-профили."""
    from pipeline.typology import run_typology

    features_wide = read_table(duckdb_path, "features_wide")
    run_typology(features_wide, duckdb_path=duckdb_path, write=True, log_mlflow=log_mlflow)


def _stage_dev_index(duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
    """Ф4: доменные баллы → схемы весов → нормировка → композитный индекс развития."""
    from pipeline.dev_index import run_dev_index

    features_wide = read_table(duckdb_path, "features_wide")
    metric_dim = read_table(duckdb_path, "metric_dim")
    run_dev_index(features_wide, metric_dim, duckdb_path=duckdb_path, write=True)


def _stage_transitions(duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
    """Ф5: ранг типов по индексу → переходы год-к-году → типология траекторий."""
    from pipeline.transitions import run_transitions

    clusters = read_table(duckdb_path, "clusters")
    dev_index = read_table(duckdb_path, "dev_index")
    run_transitions(clusters, dev_index, duckdb_path=duckdb_path, write=True)


def _stage_twins(duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
    """C2: косинусная близость z-профилей по годам → top-N статистических двойников."""
    from pipeline.twins import run_twins

    features_wide = read_table(duckdb_path, "features_wide")
    run_twins(features_wide, duckdb_path=duckdb_path, write=True)


def _stage_anomalies(duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
    """Ф9: пространственные выбросы + структурные сдвиги + кандидаты смены методологии."""
    from pipeline.anomalies import run_anomalies

    features_wide = read_table(duckdb_path, "features_wide")
    fact_region = read_table(duckdb_path, "fact_region")
    metric_dim = read_table(duckdb_path, "metric_dim")
    run_anomalies(features_wide, fact_region, metric_dim, duckdb_path=duckdb_path, write=True)


def _stage_dispersion(duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
    """Межрегиональный разброс/неравенство показателей на (метрику, год)."""
    from pipeline.dispersion import run_dispersion

    features_wide = read_table(duckdb_path, "features_wide")
    metric_dim = read_table(duckdb_path, "metric_dim")
    run_dispersion(features_wide, metric_dim, duckdb_path=duckdb_path, write=True)


#: Линейный план конвейера в порядке зависимостей (вход каждой стадии произведён выше).
STAGES: tuple[Stage, ...] = (
    Stage(
        "etl",
        _stage_etl,
        (),
        ("metric_dim", "region_dim", "fact_region"),
        "S2 ETL: сырьё → справочники и факты",
    ),
    Stage(
        "features",
        _stage_features,
        ("metric_dim", "region_dim", "fact_region"),
        ("features_wide", "metric_dim"),
        "Ф2 признаки: ядро, импутация, z-score",
    ),
    Stage(
        "typology",
        _stage_typology,
        ("features_wide",),
        ("clusters", "cluster_profile", "cluster_shap"),
        "Ф3 типология: кластеры и профили",
    ),
    Stage(
        "dev_index",
        _stage_dev_index,
        ("features_wide", "metric_dim"),
        ("dev_index",),
        "Ф4 индекс развития (3 схемы весов)",
    ),
    Stage(
        "transitions",
        _stage_transitions,
        ("clusters", "dev_index"),
        ("transitions",),
        "Ф5 переходы и траектории типов",
    ),
    Stage(
        "twins",
        _stage_twins,
        ("features_wide",),
        ("region_twins",),
        "C2 статистические двойники регионов",
    ),
    Stage(
        "anomalies",
        _stage_anomalies,
        ("features_wide", "fact_region", "metric_dim"),
        ("anomalies",),
        "Ф9 аномалии и структурные сдвиги",
    ),
    Stage(
        "dispersion",
        _stage_dispersion,
        ("features_wide", "metric_dim"),
        ("dispersion",),
        "разброс/неравенство регионов на метрику-год",
    ),
)


def stage_names() -> list[str]:
    """Список имён стадий в порядке выполнения."""
    return [s.name for s in STAGES]


def select_stages(*, only: str | None = None, from_: str | None = None) -> tuple[Stage, ...]:
    """Выбрать подмножество стадий: одну (`only`) или хвост плана с указанной (`from_`).

    Без аргументов возвращает весь план. `only` и `from_` взаимоисключающи.

    Исключения:
        ValueError: заданы оба параметра одновременно либо указано неизвестное имя стадии.
    """
    if only is not None and from_ is not None:
        raise ValueError("Параметры only и from_ взаимоисключающи")
    names = stage_names()
    if only is not None:
        if only not in names:
            raise ValueError(f"Неизвестная стадия: {only!r}. Доступные: {', '.join(names)}")
        return tuple(s for s in STAGES if s.name == only)
    if from_ is not None:
        if from_ not in names:
            raise ValueError(f"Неизвестная стадия: {from_!r}. Доступные: {', '.join(names)}")
        return STAGES[names.index(from_) :]
    return STAGES


def _verify_outputs(duckdb_path: str, stage: Stage) -> None:
    """Убедиться, что стадия записала ожидаемые контрактные таблицы (страховка прогона).

    Исключения:
        RuntimeError: одна или несколько объявленных в `writes` таблиц не появились в DuckDB.
    """
    present = set(list_tables(duckdb_path))
    missing = [t for t in stage.writes if t not in present]
    if missing:
        raise RuntimeError(f"Стадия {stage.name!r} не записала таблицы: {', '.join(missing)}")


def _execute_stage(stage: Stage, duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
    """Запустить стадию и проверить её выходы (поведение по умолчанию для run_all)."""
    log.info("stage_start", stage=stage.name, reads=list(stage.reads), writes=list(stage.writes))
    stage.run(duckdb_path, sources_path, log_mlflow)
    _verify_outputs(duckdb_path, stage)
    log.info("stage_done", stage=stage.name)


def run_all(
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    sources_path: str = DEFAULT_SOURCES_PATH,
    only: str | None = None,
    from_: str | None = None,
    log_mlflow: bool = True,
    executor: Callable[[Stage, str, str, bool], None] = _execute_stage,
) -> list[str]:
    """Последовательно выполнить выбранные стадии конвейера и вернуть их имена.

    Параметры:
        duckdb_path: путь к аналитическому хранилищу (читается и пишется стадиями);
        sources_path: реестр источников для стадии ETL;
        only / from_: запустить одну стадию или хвост плана (см. select_stages);
        log_mlflow: логировать ли типологию в MLflow (стадия typology);
        executor: исполнитель стадии (внедряется в тестах; по умолчанию — запуск + проверка).

    Возвращает:
        Имена выполненных стадий в порядке запуска.
    """
    configure_logging()
    stages = select_stages(only=only, from_=from_)
    log.info(
        "pipeline_start",
        stage="run_all",
        plan=[s.name for s in stages],
        duckdb=duckdb_path,
    )
    done: list[str] = []
    for stage in stages:
        executor(stage, duckdb_path, sources_path, log_mlflow)
        done.append(stage.name)
    log.info("pipeline_done", stage="run_all", stages_done=done)
    return done


def _print_plan() -> None:
    """Напечатать человекочитаемый план конвейера (стадии, их входы и выходы)."""
    print("План конвейера RegionLens (порядок выполнения):")
    for i, s in enumerate(STAGES, start=1):
        reads = ", ".join(s.reads) or "— (сырьё)"
        writes = ", ".join(s.writes)
        print(f"  {i}. {s.name:<12} {s.description}")
        print(f"       читает:  {reads}")
        print(f"       пишет:   {writes}")


def _build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов командной строки оркестратора."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.run_all",
        description="Воспроизводимая пересборка аналитики RegionLens (DuckDB).",
    )
    parser.add_argument("--list", action="store_true", help="показать план и выйти")
    parser.add_argument("--duckdb", default=DEFAULT_DUCKDB_PATH, help="путь к DuckDB-хранилищу")
    parser.add_argument("--sources", default=DEFAULT_SOURCES_PATH, help="путь к реестру источников")
    parser.add_argument("--no-mlflow", action="store_true", help="не логировать в MLflow")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--only", metavar="STAGE", help="запустить ровно одну стадию")
    group.add_argument(
        "--from", dest="from_", metavar="STAGE", help="запустить с указанной стадии и до конца"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Точка входа CLI: разбор аргументов и запуск конвейера (или печать плана)."""
    args = _build_parser().parse_args(argv)
    if args.list:
        _print_plan()
        return
    run_all(
        duckdb_path=args.duckdb,
        sources_path=args.sources,
        only=args.only,
        from_=args.from_,
        log_mlflow=not args.no_mlflow,
    )


if __name__ == "__main__":
    main()
