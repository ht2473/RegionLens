"""Сценарий нагрузочного тестирования (Ф12a-харнесс): read-only API поверх предрасчёта.

Цель — измерять отклик «горячих» эндпойнтов (карта, дашборд региона, рейтинг, типология,
переходы) для подтверждения целевого <200 мс из §11.2 Хартии. Реальные okato берутся из
`/api/regions/` один раз при старте, годы — из окна анализа 2010–2024, чтобы запросы были
валидными (200), а не 404. Веса задач отражают частоту реальных сценариев аналитика.

Запуск (нужен поднятый сервер на :8000 и собранная DuckDB):
    locust -f tests/load/locustfile.py --host http://127.0.0.1:8000
Безголовый замер (50 пользователей, ramp 10/с, 1 минута):
    locust -f tests/load/locustfile.py --host http://127.0.0.1:8000 --headless -u 50 -r 10 -t 1m
"""

from __future__ import annotations

import random

from locust import HttpUser, between, task

# Годы окна анализа (Хартия §3): по ним есть типология/индекс/переходы.
_YEARS = list(range(2010, 2025))
_MEASURES = ("cluster", "index")
_SCHEMES = ("equal", "pca", "expert")
_FALLBACK_OKATO = "45000000"  # на случай, если /api/regions/ недоступен на старте


class RegionLensUser(HttpUser):
    """Имитация аналитика, листающего карту, дашборды регионов и рейтинги."""

    wait_time = between(0.2, 1.0)
    okatos: list[str] = []

    def on_start(self) -> None:
        """Один раз получить реальный список okato — чтобы все запросы были валидными."""
        try:
            data = self.client.get("/api/regions/", name="/api/regions/").json()
            self.okatos = [row["okato"] for row in data if "okato" in row]
        except Exception:  # на старте сеть/формат могут подвести — не валим пользователя
            self.okatos = []

    def _okato(self) -> str:
        """Случайный валидный okato (или запасной, если список пуст)."""
        return random.choice(self.okatos) if self.okatos else _FALLBACK_OKATO

    @task(5)
    def geo_layer(self) -> None:
        """Слой карты — самый частый запрос (раскраска по кластеру/индексу)."""
        year = random.choice(_YEARS)
        measure = random.choice(_MEASURES)
        self.client.get(f"/api/geo/layer/?year={year}&measure={measure}", name="/api/geo/layer/")

    @task(4)
    def region_dashboard(self) -> None:
        """Дашборд региона (индекс по доменам + кластер + SHAP-топ)."""
        year = random.choice(_YEARS)
        self.client.get(f"/api/regions/{self._okato()}/?year={year}", name="/api/regions/[okato]/")

    @task(3)
    def index_ranking(self) -> None:
        """Рейтинг/индекс на год по выбранной схеме весов."""
        year = random.choice(_YEARS)
        scheme = random.choice(_SCHEMES)
        self.client.get(f"/api/index/?year={year}&scheme={scheme}", name="/api/index/")

    @task(2)
    def typology(self) -> None:
        """Кластеры на год (слой обзора типологии)."""
        year = random.choice(_YEARS)
        self.client.get(f"/api/typology/?year={year}", name="/api/typology/")

    @task(2)
    def transitions(self) -> None:
        """Переходы и тип траектории региона."""
        self.client.get(f"/api/transitions/?okato={self._okato()}", name="/api/transitions/")

    @task(1)
    def regions_list(self) -> None:
        """Справочник регионов (лёгкий запрос-список)."""
        self.client.get("/api/regions/", name="/api/regions/")
