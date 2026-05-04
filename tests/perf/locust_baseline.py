"""Wave 7.6 — locust baseline нагрузочный профиль.

Альтернатива k6 на чистом Python (зависимость в `[project.optional-dependencies] perf`).

Запуск (headless)::

    locust -f tests/perf/locust_baseline.py \\
        --host=http://127.0.0.1:8000 \\
        --users 100 --spawn-rate 10 --run-time 3m \\
        --headless

Целевые SLO (V10 #14): p95 < 200ms, RPS > 1000, error < 1%.
"""

from __future__ import annotations

from locust import HttpUser, between, task


class HealthcheckUser(HttpUser):
    """Базовый профиль: каждый VU дёргает ``/api/v1/health``."""

    wait_time = between(0.05, 0.2)

    @task(weight=10)
    def healthcheck(self) -> None:
        """Smoke-эндпоинт для измерения накладных расходов middleware-стека."""
        with self.client.get("/api/v1/health", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"unexpected status {resp.status_code}")

    @task(weight=1)
    def readiness(self) -> None:
        """Readiness — проверяет полный resilience-coordinator chain."""
        with self.client.get("/api/v1/readiness", catch_response=True) as resp:
            if resp.status_code not in (200, 503):
                resp.failure(f"unexpected readiness status {resp.status_code}")
