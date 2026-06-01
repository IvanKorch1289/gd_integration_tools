# chaos-test debugging runbook

К5 (Wave K5/chaos-tests). Suite — 11 канонических resilience chains × 3
сценария = 33 теста под маркером `pytest.mark.chaos`.

## Запуск локально

```bash
# Требуется Docker + toxiproxy образ
make chaos
```

или напрямую:

```bash
uv run pytest tests/chaos -q -m chaos
```

Без Docker фикстура `toxiproxy` (см. `testkit/fixtures/toxiproxy.py`)
выставляет `pytest.skip` — тесты помечаются `s` в выводе.

## Отладка падающего сценария

1. **Локализуйте chain**: каждый файл `tests/chaos/test_<chain>_chain_chaos.py`
   проверяет один chain. Выявляйте фактический chain по последней строке вывода
   `pytest -v`.
2. **Проверьте сценарий**: параметризация `slow / error / disconnect` —
   `parametrize` с `@pytest.fixture` `chaos_chain` (`tests/chaos/conftest.py`).
3. **Посмотрите toxiproxy state**:
   ```bash
   curl http://localhost:8474/proxies
   ```
4. **Сбросьте все toxic'и**:
   ```bash
   curl -X POST http://localhost:8474/reset
   ```

## Как диагностировать regression

* `slow` — проверьте `core/resilience/breaker.py` (TimeLimit toxic);
  CB должен **открыться** после 5+ slow-вызовов.
* `error` — проверьте `core/resilience/retry.py` + chain fallback link;
  ожидаемое поведение — CB OPEN + fallback active.
* `disconnect` — проверьте reconnection-логику в backend client'е;
  ожидаемое поведение — `ImmediateFallback` после первого rejection.

## CI

`.github/workflows/chaos.yml`:
* `schedule '0 4 * * *'` (nightly, 25 мин timeout);
* `workflow_dispatch`;
* `pull_request` если затронуты `src/backend/{infrastructure,core}/resilience/**`
  или `tests/chaos/**`.

Артефакт `chaos-results.xml` (junit) хранится 14 дней.

## Что **не** делает chaos suite

* **не** бьёт по DSL routes — это потребует К2 (RouteLoader full-cycle, Sprint 2);
  до тех пор chains тестируются напрямую.
* **не** проверяет SLO под нагрузкой — это perf-suite (`make perf-gate`).

После закрытия К2 будет добавлена follow-up Wave с
`tests/chaos/test_route_<X>_chaos.py` через `testkit.RouteRunner`.
