"""К5 (Wave K5/perf-gate) — расширенный locust-профиль.

Имитирует более правдоподобный mix запросов: orders / health / admin-routes.

Запуск (headless)::

    uv run --extra perf locust -f tests/perf/locust_full_profile.py \\
        --host=http://127.0.0.1:8000 --users 100 --spawn-rate 10 \\
        --run-time 3m --headless

SLO (V10 #14): p95 < 200ms, RPS > 1000, error < 1%.
"""

from __future__ import annotations

from locust import HttpUser, between, task


class IntegrationBusUser(HttpUser):
    """Mixed-profile нагрузка: health + admin-routes + dsl-invoke."""

    wait_time = between(0.05, 0.2)

    @task(weight=8)
    def healthcheck(self) -> None:
        """Smoke-эндпоинт — самый высокий вес."""
        with self.client.get("/api/v1/health", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"unexpected status {resp.status_code}")

    @task(weight=3)
    def admin_routes(self) -> None:
        """List routes — read-heavy, проверяет middleware-стек."""
        with self.client.get("/api/v1/admin/routes", catch_response=True) as resp:
            if resp.status_code >= 500:
                resp.failure(f"server error {resp.status_code}")

    @task(weight=2)
    def admin_actions(self) -> None:
        """List actions — отдельный read-heavy путь."""
        with self.client.get("/api/v1/admin/actions", catch_response=True) as resp:
            if resp.status_code >= 500:
                resp.failure(f"server error {resp.status_code}")

    @task(weight=1)
    def readiness(self) -> None:
        """Readiness — проверяет full resilience-coordinator chain."""
        with self.client.get("/api/v1/readiness", catch_response=True) as resp:
            if resp.status_code not in (200, 503):
                resp.failure(f"unexpected readiness status {resp.status_code}")
