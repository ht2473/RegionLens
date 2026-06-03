"""Оркестратор конвейера: единая команда пересборки всей аналитики.

Запуск: `python -m pipeline.run_all` (или `make pipeline`). Стадии S1–S9 подключаются
по мере реализации (Ф1–Ф9). Сейчас — каркас: логирует план и корректно завершается
(нужно для воспроизводимого прогона `make all` и smoke-теста Ф0).
"""

from pipeline.logging_setup import configure_logging, log

# План стадий конвейера (заполняется реализациями в Ф1–Ф9).
STAGES: list[str] = [
    # "S1_ingest", "S2_etl", "S3_features", "S4_typology", "S5_index",
    # "S6_transitions", "S7_forecast", "S8_anomalies", "S9_publish",
]


def run_all() -> None:
    """Последовательно выполнить все зарегистрированные стадии конвейера."""
    configure_logging()
    log.info("pipeline_start", stage="run_all", stages_registered=len(STAGES))
    for name in STAGES:
        log.info("stage_skipped_not_implemented", stage=name)
    log.info("pipeline_done", stage="run_all")


if __name__ == "__main__":
    run_all()
