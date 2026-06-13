"""Тесты оркестратора конвейера (pipeline.run_all).

Проверяют логику плана без обращения к данным: связность DAG по объявленным
входам/выходам, выбор подмножества стадий (--only/--from), порядок выполнения и
проверку выходов. Реальные run_*-функции подменяются внедряемым исполнителем.
"""

from __future__ import annotations

import pytest

from pipeline.run_all import (
    STAGES,
    Stage,
    _verify_outputs,
    run_all,
    select_stages,
    stage_names,
)


def test_dag_inputs_are_produced_by_earlier_stages() -> None:
    """Топологическая связность: каждый вход стадии произведён одной из предыдущих.

    Пустой `reads` означает чтение сырья (стадия ETL) и не требует предшественника.
    """
    produced: set[str] = set()
    for stage in STAGES:
        for table in stage.reads:
            assert table in produced, (
                f"стадия {stage.name!r} читает {table!r} раньше, чем он создан"
            )
        produced.update(stage.writes)


def test_every_stage_writes_at_least_one_table() -> None:
    """Каждая стадия должна объявлять хотя бы одну выходную таблицу."""
    for stage in STAGES:
        assert stage.writes, f"стадия {stage.name!r} не объявляет выходов"


def test_stage_names_unique() -> None:
    """Имена стадий уникальны (нужно для корректной работы --only/--from)."""
    names = stage_names()
    assert len(names) == len(set(names))


def test_select_default_returns_full_plan() -> None:
    """Без аргументов выбирается весь план в исходном порядке."""
    assert select_stages() == STAGES


def test_select_from_returns_tail() -> None:
    """--from возвращает хвост плана начиная с указанной стадии включительно."""
    names = stage_names()
    pivot = names[2]
    tail = select_stages(from_=pivot)
    assert [s.name for s in tail] == names[2:]


def test_select_only_returns_single() -> None:
    """--only возвращает ровно одну запрошенную стадию."""
    selected = select_stages(only="twins")
    assert [s.name for s in selected] == ["twins"]


def test_select_only_and_from_conflict() -> None:
    """Одновременное указание only и from_ запрещено."""
    with pytest.raises(ValueError, match="взаимоисключающи"):
        select_stages(only="twins", from_="etl")


@pytest.mark.parametrize("kwargs", [{"only": "ghost"}, {"from_": "ghost"}])
def test_select_unknown_stage_raises(kwargs: dict[str, str]) -> None:
    """Неизвестное имя стадии в only/from_ приводит к ValueError."""
    with pytest.raises(ValueError, match="Неизвестная стадия"):
        select_stages(**kwargs)


def test_run_all_executes_in_plan_order() -> None:
    """run_all выполняет стадии в порядке плана и возвращает их имена."""
    calls: list[str] = []

    def fake_executor(stage: Stage, duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
        calls.append(stage.name)

    done = run_all(executor=fake_executor)
    assert calls == stage_names()
    assert done == calls


def test_run_all_from_runs_only_tail() -> None:
    """run_all(from_=...) запускает только хвост плана."""
    calls: list[str] = []

    def fake_executor(stage: Stage, duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
        calls.append(stage.name)

    done = run_all(from_="dev_index", executor=fake_executor)
    expected = stage_names()[stage_names().index("dev_index") :]
    assert calls == expected
    assert done == expected


def test_run_all_only_runs_single_stage() -> None:
    """run_all(only=...) запускает ровно одну стадию."""
    calls: list[str] = []

    def fake_executor(stage: Stage, duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
        calls.append(stage.name)

    done = run_all(only="anomalies", executor=fake_executor)
    assert calls == ["anomalies"]
    assert done == ["anomalies"]


def test_run_all_threads_paths_and_mlflow_flag() -> None:
    """run_all пробрасывает пути и флаг MLflow в исполнитель без изменений."""
    seen: list[tuple[str, str, bool]] = []

    def fake_executor(stage: Stage, duckdb_path: str, sources_path: str, log_mlflow: bool) -> None:
        seen.append((duckdb_path, sources_path, log_mlflow))

    run_all(
        duckdb_path="x.duckdb",
        sources_path="y.yaml",
        log_mlflow=False,
        only="twins",
        executor=fake_executor,
    )
    assert seen == [("x.duckdb", "y.yaml", False)]


def test_verify_outputs_raises_on_missing_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """_verify_outputs падает, если объявленная выходная таблица не записана."""
    monkeypatch.setattr("pipeline.run_all.list_tables", lambda _path: ["metric_dim"])
    stage = STAGES[0]  # etl: пишет три таблицы, в наличии лишь одна
    with pytest.raises(RuntimeError, match="не записала таблицы"):
        _verify_outputs("ignored.duckdb", stage)


def test_verify_outputs_passes_when_all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """_verify_outputs не падает, когда все выходные таблицы стадии присутствуют."""
    etl = STAGES[0]
    monkeypatch.setattr("pipeline.run_all.list_tables", lambda _path: list(etl.writes) + ["extra"])
    _verify_outputs("ignored.duckdb", etl)  # не должно бросить исключение
