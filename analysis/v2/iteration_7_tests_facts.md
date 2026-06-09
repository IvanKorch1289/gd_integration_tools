# V2 Итерация 7: Тесты — фактические находки

## Тестовая статистика
- `def test_` в tests/: **10,777** тест-функций
- `@pytest.mark.skip`: **23**
- `@pytest.mark.xfail`: **13**
- `@pytest.mark.flaky`: **0** (нет pytest-rerunfailures)
- e2e файлы с тестами: **1** (не 0 как в V1, но всё равно минимум)

## CI
- `.coverage` файл есть (69632 байт, 2026-06-08)
- `coverage.json` baseline не читается (формат отличается от ожидаемого)
- pytest-xdist **не используется в CI** (test.yml)

## Покрытие
- `.baselines/coverage.json` — формат не стандартный, `totals.percent_covered` = N/A
- Нужен `coverage report` или `pytest-cov` output для точных цифр
