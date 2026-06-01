# Run chaos locally

Запустить chaos × 33 (11 chains × 3 toxiproxy сценария).

## Предусловия

* Docker daemon доступен;
* `uv sync --extra testkit` (поднимает `testcontainers`);
* `pytest tests/chaos --collect-only -q` отдаёт 33 теста.

## Запуск

```bash
make chaos
```

Или напрямую:

```bash
uv run pytest tests/chaos -q -m chaos
```

Без Docker фикстура `toxiproxy` (см. `testkit/fixtures/toxiproxy.py`)
выставляет `pytest.skip` — тесты помечаются как skipped, не падают.

## Отладка

См. полный runbook: [chaos-test-debug](../runbooks/chaos-test-debug.md).
