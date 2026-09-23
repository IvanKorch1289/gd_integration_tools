# ADR-0335 — Configuration matrix gate: unsafe secret defaults detector

## Статус

**Accepted** (2026-09-23). Реализует configuration matrix gap из
стратегического анализа 2026-09-22.

## Контекст

Стратегический анализ (timestamp 1790089356160) выделил configuration
matrix как один из приоритетных gaps:

| Проверка | Назначение |
|---|---|
| Все обязательные prod-параметры заданы | Не допустить скрытого fallback |
| Неизвестные переменные запрещены | Выявить опечатки |
| Deprecated variables вызывают ошибку или warning | Управлять миграцией конфигурации |
| **Secret не имеет небезопасного default** | **Исключить bootstrap credentials** |
| Feature dependencies разрешимы | Не включить функцию без backend |
| Profiles проходят startup smoke | Проверить composition root |

Из всего списка проверка "Secret не имеет небезопасного default"
наиболее чётко формализуется через статический анализ Pydantic
Settings — без Docker, без runtime, без live инфраструктуры.

## Решение

Добавить новый focused gate
``tools/checks/check_unsafe_defaults.py`` (AST-based, без импортов
конфигов), который сканирует все Settings в
``src/backend/core/config/`` и детектирует:

### HIGH severity (exit 1, fail-closed)

1. **SecretStr / SecretBytes поле с non-empty default**: например
   ``api_key: SecretStr = Field(default=SecretStr("hardcoded-key"))``.
   Это значит, что в коде лежит реальный hardcoded secret.

2. **str поле (НЕ SecretStr) с placeholder default**: например
   ``api_key: str = Field(default="changeme")``. Имя поля похоже на
   секрет (password, secret, api_key, token, bind_password и т.д.),
   значение совпадает с известным placeholder-паттерном (changeme,
   password, secret, admin, test, demo, your-key-here, <...>, xxx,
   placeholder, TODO, fixme).

### MEDIUM severity (warning, exit 0; --strict превращает в exit 1)

**SecretStr с default=SecretStr("")**: пустая строка вместо ``None``
— code smell, но не security issue (значение всё равно проверяется
на пустоту в коде).

### LOW severity (info, exit 0)

**str поле с default="" и именем как секрет**: рекомендация перейти
на ``SecretStr | None = None`` для явного маркера "не задан". Не
критично, но улучшает safety.

### Архитектурные решения

- **AST-based без импортов конфигов** — gate запускается быстро и
  не требует установленных зависимостей (например, ``hvac`` для
  Vault). По этой же причине существующий
  ``tools/check_env_example.py`` использует AST.

- **Placeholder-паттерны как regex** — компактный список типичных
  bootstrap credentials, легко расширяется.

- **Secret field name detection** — эвристика по имени поля
  (``password``, ``api_key``, ``token``, ``signature_secret`` и т.д.),
  НЕ только по типу (``SecretStr``). Это ловит случаи, когда поле
  объявлено как ``str``, но логически является секретом.

- **Backward-compat с pytest ``--import-mode=importlib``** — тесты
  используют ``importlib.util.spec_from_file_location`` workaround
  (прецедент: 8+ test files, см. PROGRESS_LEDGER).

- **Typer+rich для CLI** (per ADR-0084 / W6 P1-8): ``--strict`` для
  fail на MEDIUM, ``--json`` для machine-readable output (через
  ``sys.stdout.write`` — допустимо для JSON-piping).

- **Settings class heuristic** — ``XxxSettings`` / ``XxxConfig``
  suffix, либо ``BaseSettings*`` в bases. Не ловит классы с
  ``Not``-prefix (NotSettings, NotConfig) — explicit exclusion для
  избежания false positives.

## Альтернативы (отклонённые)

- **Расширить существующий ``check_env_example.py``** — отклонено:
  задачи разные (env vars в Settings vs unsafe defaults), смешивание
  затруднит maintenance.

- **Pydantic ``SecretStr`` strict type-check** — отклонено: не все
  секретные поля объявлены как SecretStr (многие остались str по
  историческим причинам), gate должен ловить и str.

- **Runtime-проверка через DI** — отклонено: требует загрузки
  конфигов и всех зависимостей, медленно и brittle. Статанализ
  достаточно для обнаружения hardcoded placeholders.

- **Fail на всех MEDIUM/LOW** — отклонено: 19 существующих LOW
  violations в репо (все str='' для secret-named полей) — не
  критично, нужно incremental migration. ``--strict`` flag даёт
  opt-in жёсткости.

## Последствия

- **0 HIGH, 0 MEDIUM, 19 LOW** violations в текущем HEAD — нет
  hardcoded placeholders, нет критичных code smell'ов. Все 19 LOW —
  рекомендации мигрировать на ``SecretStr | None = None``.

- **Gate безопасен для CI**: без HIGH/MEDIUM exit 0, можно включать
  в blocking lint.

- **Расширяемость**: новые placeholder-паттерны добавляются в
  ``_PLACEHOLDER_PATTERNS``; новые secret field names — в
  ``_SECRET_FIELD_NAMES``.

- **Параллельно к ``check_env_example.py``**: два независимых
  configuration gate'а, каждый со своей зоной ответственности.

## Verification

| Gate | Команда | Результат |
|---|---|---|
| compileall | `python -m compileall -q src/ extensions/ scripts/ tools/ tests/ testkit/` | EXIT 0 |
| check_python3_syntax | `python tools/checks/check_python3_syntax.py --root .` | EXIT 0 |
| ruff | `python -m ruff check tools/checks/check_unsafe_defaults.py` | All checks passed |
| pytest | `python -m pytest tests/unit/tools/test_w11_p0_2_check_unsafe_defaults.py` | 63/63 passed |
| pytest (scaffold) | `python -m pytest tests/unit/tools/test_w6_p1_8_phase10_scaffold_typer.py` | 10/10 passed |
| real-repo scan | `python tools/checks/check_unsafe_defaults.py` | 0 HIGH, 0 MEDIUM, 19 LOW, EXIT 0 |

## Файлы

- `tools/checks/check_unsafe_defaults.py` — новый tool (350 LOC)
- `tests/unit/tools/test_w11_p0_2_check_unsafe_defaults.py` — 63 tests
- `tools/scaffold.py` — typer-миграция (Phase 10, файлы ADR/test
  были в `180e75819`, но сам файл не был закоммичен)
- `docs/adr/INDEX.md` — обновлён (127 → 128 ADRs)

## Ссылки

- ADR-0084 — typer+rich CLI pattern
- ADR-0334 — fact-check master state (стратегический анализ)
- W6 P1-8 Phase 3-10 — typer+rich миграции tools
- PROGRESS_LEDGER: `docs/roadmap/PROGRESS_LEDGER.md`
