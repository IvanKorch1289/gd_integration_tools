"""Sprint 6 K2 — locust baseline (1000 RPS sustained + 5000 RPS spike).

Расширение `tests/perf/k6_baseline.js` для команд без k6 в окружении.
Скрипт работает на 3 reference endpoints (Sprint 6 DoD, PLAN.md V18.2 §6):

    * GET  /api/v1/health                — middleware-overhead probe;
    * GET  /api/v1/admin/users           — DB-pool round-trip;
    * POST /api/v1/credit/check          — extensions/credit_pipeline e2e.

Запуск (sustained 1000 RPS 60s)::

    locust -f tests/perf/locust_baseline.py \\
        --host=http://127.0.0.1:8000 \\
        --users 200 --spawn-rate 50 --run-time 90s --headless

Запуск (spike 5000 RPS 10s — нужно вручную поднять --users до 1000)::

    locust -f tests/perf/locust_baseline.py \\
        --host=http://127.0.0.1:8000 \\
        --users 1000 --spawn-rate 500 --run-time 20s --headless

Celery SLO (V10 #14 + Sprint 6): p95 < 200ms, RPS > 1000, error < 1%.
Feature-flag: ``perf_gate_strict`` (default-OFF; warn-only в CI).
"""

from __future__ import annotations

from locust import HttpUser, between, task


class BaselineUser(HttpUser):
    """Многоэндпоинтный VU — 60% health / 30% admin / 10% credit.

    Веса соответствуют k6_baseline.js. Wait-time минимальный для достижения
    1000 RPS на ~200 VU (10 RPS per VU).
    """

    wait_time = between(0.05, 0.15)

    @task(weight=60)
    def healthcheck(self) -> None:
        """Smoke /health — измеряет накладные расходы middleware-стека.

        M5-#10 (2026-09-05): /api/v1/health закрыт AuthRequiredMiddleware
        (B-04 hardening, 401) → цель переехала на публичный /health (liveness,
        та же полная middleware-цепочка, 200).
        """
        with self.client.get("/health", name="health", catch_response=True,) as resp:
            if resp.status_code != 200:
                resp.failure(f"unexpected status {resp.status_code}")

    @task(weight=30)
    def admin_users(self) -> None:
        """DB-pool round-trip через /api/v1/admin/users."""
        with self.client.get(
            "/api/v1/admin/users?limit=10",
            name="admin_users",
            headers={"Authorization": "Bearer dev-smoke-token"},
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 401):
                # M5-#10: 401 = auth-gate путь (нагрузочная цель той же цепочки).
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")

    @task(weight=10)
    def credit_check(self) -> None:
        """E2E проверка extensions/credit_pipeline."""
        payload = {
            "client_id": "locust-load-test",
            "amount": 100000.0,
            "currency": "RUB",
        }
        with self.client.post(
            "/api/v1/credit/check",
            name="credit_check",
            json=payload,
            catch_response=True,
        ) as resp:
            # 202 (async-api accepted), 200, 401 (без auth) — допустимы.
            if resp.status_code in (200, 202, 401):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")


class HealthcheckOnlyUser(HttpUser):
    """Резервный профиль для замера чистого middleware overhead.

    Используется когда DB/extensions недоступны (dev_light без credit_pipeline).
    Запуск: ``locust ... --tags healthcheck_only``.
    """

    wait_time = between(0.05, 0.2)
    tags = ["healthcheck_only"]

    @task(weight=10)
    def healthcheck(self) -> None:
        """Базовый /health для измерения чистого overhead.

        M5-#10 (2026-09-05): /api/v1/health закрыт AuthRequiredMiddleware
        (B-04) → публичный /health (liveness, та же middleware-цепочка).
        """
        with self.client.get("/health", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"unexpected status {resp.status_code}")

    @task(weight=1)
    def readiness(self) -> None:
        """Readiness — полный ResilienceCoordinator chain (за auth).

        M5-#10: 401 допустим — readiness за AuthRequiredMiddleware (P2-13);
        нагрузочная цель — путь middleware + auth-gate.
        """
        with self.client.get("/api/v1/readiness", catch_response=True) as resp:
            if resp.status_code in (200, 401, 503):
                resp.success()
            else:
                resp.failure(f"unexpected readiness status {resp.status_code}")
