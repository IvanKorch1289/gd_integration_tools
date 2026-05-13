# ADR-0055 — Chaos Engineering + Performance Gate

* Статус: Accepted (Sprint 3, К2 W3, 2026-05-13)
* Связано с: V15 R-V15-10, R-V15-14; PLAN.md V18.1 §S3 К2 W3 + perf-gate.

## Контекст

R-V15-10 (auto-scaling 3 уровня) и R-V15-14 (connection pools обязательно)
требуют доказательной устойчивости интеграционной шины к сетевым отказам,
timeouts, throttling и connection-leak'ам. Текущее покрытие resilience-тестами
< 5%; нет инфраструктуры для controlled fault-injection в integration-окружении.

Целевые сценарии fault-injection (33 теста, 3 batch):

* Batch 1 (W2) — cache/breaker/retry/timeout — 11 тестов;
* Batch 2 (W2) — redis/graylog/vault/clickhouse — 11 тестов;
* Batch 3 (W3) — outbox/inbox/sse/websocket/temporal — 11 тестов.

## Решение

1. **Toxiproxy как fault-injection layer** — Shopify toxiproxy запускается
   в ``docker-compose.dev.yml`` (порт ``8474``) и проксирует PG/Redis/Kafka/etc.
   Тесты прикрепляют toxics (``latency``, ``bandwidth``, ``timeout``,
   ``slow_close``) через ``toxiproxy-python`` SDK и проверяют, что breaker
   открывается, retry срабатывает, и fallback chain выдерживает SLO.

2. **Testkit chaos-fixtures** — ``src/backend/testkit/chaos_fixtures.py``
   предоставляет 4 helper'а:
   * ``with_latency(proxy, ms)`` — context manager, добавляет latency-toxic;
   * ``with_timeout(proxy, ms)`` — timeout-toxic;
   * ``with_bandwidth(proxy, kbps)`` — bandwidth-toxic;
   * ``connection_killer(proxy)`` — резкое разрыв соединения.
   + 3 injectors (slow_close / reset_peer / down).

3. **Chaos-marker + GitHub gating** — все chaos-тесты помечены
   ``@pytest.mark.chaos`` + ``@pytest.mark.requires_toxiproxy``. CI собирает
   их в отдельный job ``test-chaos.yml`` (на schedule + push в release-ветки);
   PR-job собирает только без выполнения (``pytest --collect-only -m chaos``).

4. **Performance gate** — ``tools/perf_gate.py`` запускает locust-сценарии
   (``tests/perf/scenarios/*.py``) с пороговыми проверками:
   * RPS-floor (минимум 1000 RPS на baseline endpoint);
   * p95-latency (< 200 ms);
   * p99-latency (< 500 ms);
   JSON-отчёт пишется в ``tests/perf/reports/perf_<timestamp>.json``.
   CI-gate fails если любой порог не выполнен.

5. **Cardinality budget для OTel** — отдельный gate
   ``tools/check_cardinality_budget.py`` проверяет, что метрик-cardinality
   < 100k (агрегация Prometheus); high-cardinality metrics обнаруживаются
   через rules в ``infrastructure/observability/otel/cardinality.py``.

## Последствия

* `+` Доказательная резилентность критических путей; breaker/retry/fallback
  работают согласно SLO под controlled fault-injection.
* `+` Toxiproxy не требует production-доступа — все тесты гоняются в isolated
  docker-network.
* `+` Performance-gate ловит регрессии p95/p99 до merge; latency budget — RBA.
* `−` Chaos-batches требуют toxiproxy-container в CI (slot ~50 MB RAM,
  ~3 сек startup); запускаются только on-schedule (nightly + on-release).
* `−` Locust-сценарии требуют warmup-фазы (60 сек) — увеличивает CI job time.

## Альтернативы рассмотрены и отклонены

* **Chaos Mesh** — отклонено: требует Kubernetes (избыточно для CI).
* **Pumba** — отклонено: Docker-only, нет интеграции с pytest-fixtures.
* **Litmus** — отклонено: ориентирован на k8s, ML-overhead.
* **k6 для perf-gate** — рассмотрено, но locust выбран из-за Python-нативности
  (можно делать complex scenarios без отдельного скриптинг-языка).

## CI gates (Sprint 3 К2 W2-W3)

* ``make chaos`` — запуск chaos-тестов локально (требует toxiproxy).
* ``make perf-gate`` — perf-gate скрипт (требует locust + perf scenarios).
* ``make chaos-slow`` — full nightly chaos suite.
* ``make coverage-gate`` — coverage ≥ 35% (W3).

## Зависимости (Sprint 3 W2-W3)

* ``toxiproxy-python>=0.1.1,<1.0.0`` (dev-group).
* ``locust>=2.43.4`` (уже в ``[perf]`` extras).
* ``schemathesis>=3.27`` (Sprint 6 — API fuzz, для совместимости).
