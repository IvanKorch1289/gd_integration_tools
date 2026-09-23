# ADR-0336 — W11 P0-3: Configuration matrix — required secrets & unknown vars

## Статус

**Accepted** (2026-09-23). Расширяет W11 P0-2 (ADR-0335) для закрытия
configuration matrix gap из стратегического анализа 2026-09-22.

## Контекст

Стратегический анализ (timestamp 1790089356160) выделил configuration
matrix как приоритетный gap. W11 P0-2 (ADR-0335) закрыл проверку
"Secret не имеет небезопасного default" через `check_unsafe_defaults.py`.

W11 P0-3 закрывает ещё **три проверки** (расширяя существующий
`tools/check_env_example.py`):

| Проверка | Назначение |
|---|---|
| **Все обязательные prod-параметры заданы** | Не допустить скрытого fallback |
| **Required secrets в .env.example** | Bootstrap credentials обязаны быть declared |
| **Неизвестные переменные запрещены** | Выявить опечатки |

## Проблемы найденные в существующем коде

При аудите `tools/check_env_example.py` (W6 P1-8 Phase 3) обнаружены
два pre-existing бага, которые маскировали matrix gap:

### Bug 1: CONFIG_DIR указывал на несуществующий путь

```python
# БЫЛО (Phase 3, 2026-09):
CONFIG_DIR = PROJECT_ROOT / "src" / "core" / "config"  # ❌ не существует!

# СТАЛО (W11 P0-3):
CONFIG_DIR = PROJECT_ROOT / "src" / "backend" / "core" / "config"  # ✅
```

Tool находил **0 env vars** (вместо ~958), поэтому всегда exit 0.
Pre-existing тихий bug от Phase 3.

### Bug 2: Class detection только через BaseSettings в bases

```python
# БЫЛО: требовало {"BaseSettings", "BaseSettingsWithLoader"} в bases
if not ({"BaseSettings", "BaseSettingsWithLoader"} & bases):
    continue

# СТАЛО: также детектит Settings через env_prefix в model_config
prefix = ""  # extracted из model_config = SettingsConfigDict(env_prefix=...)
is_settings = bool(prefix) or has_settings_base
```

В репо 99% Settings используют inline `SettingsConfigDict(env_prefix=...)`
без `BaseSettings` в bases (только `BaseModel`). Старая логика ловила
только ~5% Settings.

## Решение

Расширить `tools/check_env_example.py`:

### Новые CLI flags

1. **`--matrix`** — расширенная matrix-проверка:
   - Required secret vars (`Field(...)` или `Field(description=...)` без
     default для имён вида `api_key`, `password`, `token`, ...)
     **должны** быть в `.env.example` → иначе **fail (exit 1)**.

2. **`--json`** — machine-readable output для CI integration.

### Изменённое поведение default mode

Раньше default mode fail на missing (exit 1) — из-за бага Bug 1 это
никогда не срабатывало. Теперь, когда Bug 1 исправлен:
- **default mode**: warn на missing (exit 0) — soft check, потому что
  в репо convention — `.env.example` хранит ТОЛЬКО секреты, остальное в
  `config_profiles/{profile}.yml`.
- **`--strict`**: hard fail на missing (exit 1) — для проектов, где
  ВСЁ в `.env.example`.

### Новые helper функции

- `collect_required_secret_env_vars()` — required + secret-named fields.
- `_is_secret_field_name()` — общая эвристика с `check_unsafe_defaults.py`.

## Результаты на текущем HEAD (`a9a763561`)

После исправления CONFIG_DIR и class detection:

| Метрика | До фикса | После фикса |
|---|---|---|
| Env vars в Settings | 0 (bug) | **958** |
| Vars в .env.example | 56 | 56 |
| Missing (warning) | 0 | 902 (non-secret, в YAML) |
| Extra (typo guard) | 56 | 56 |
| **Required secrets missing (matrix)** | 0 (bug) | **11** |

### 11 required secrets, отсутствующих в `.env.example` (REAL gaps)

```
CLICKHOUSE__PASSWORD     # CH пароль (обязателен для production)
DADATA__API_KEY          # DaData.ru API ключ
ES__API_KEY              # Elasticsearch API key
ES__PASSWORD             # Elasticsearch пароль
FS__ACCESS_KEY           # S3 access key
MONGO__PASSWORD          # MongoDB пароль
RAG__EMBEDDING_API_KEY   # RAG embedding провайдер API ключ
RAG__QDRANT_API_KEY      # Qdrant API ключ
SEC__API_KEY             # Security API ключ
SEC__ROUTES_WITHOUT_API_KEY  # Routes без API ключа
SKB__API_KEY             # SKB API ключ
```

Эти gaps подтверждают ценность matrix-проверки — без неё эти required
секреты остались бы незадокументированными (silent fallback при deploy).

## Альтернативы (отклонённые)

- **Создать отдельный `check_config_matrix.py`** — отклонено:
  расширение существующего tool чище, меньше поверхность для
  поддержки, общий импорт helper'ов.

- **Fail default на missing** — отклонено: 902 non-secret vars в YAML
  profiles → false positives. Soft-warn + --strict для hard fail.

- **Парсить config_profiles/*.yml** — отклонено: требует YAML parser
  + schema, расширение scope. Будущий W11 P1+ (отдельная задача).

- **Fail на unknown vars** — отклонено: 56 unknown vars в текущем HEAD
  (APP_PROFILE, APP_ENV, CDC_ENABLED, ...) — это намеренно
  документированные "control plane" vars без Settings-обёртки. Fail
  был бы false positive.

## Последствия

- **W11 P0-3 matrix gate готов к CI integration**:
  `python tools/check_env_example.py --matrix` → exit 1 если есть
  required secrets без `.env.example` декларации.

- **Pre-existing bugs исправлены** (CONFIG_DIR path + class detection):
  tool теперь действительно проверяет env var coverage.

- **Documentation обновлена** (этот ADR + W11 P0-3 entry в
  PROGRESS_LEDGER).

- **Backward-compat сохранён**: pre-existing test
  `test_w6_p1_8_phase3_check_env_example_typer.py` обновлён для
  учёта `--json` (sys.stdout.write для machine-readable output).

## Verification

| Gate | Команда | Результат |
|---|---|---|
| compileall | `python -m compileall -q src/ extensions/ scripts/ tools/ tests/ testkit/` | EXIT 0 |
| check_python3_syntax | `python tools/checks/check_python3_syntax.py --root .` | EXIT 0 |
| ruff | `python -m ruff check tools/check_env_example.py tests/...` | All checks passed |
| pytest (matrix) | `python -m pytest tests/unit/tools/test_w11_p0_3_check_env_example_matrix.py` | 29/29 passed |
| pytest (back-compat) | `python -m pytest tests/unit/tools/test_w6_p1_8_phase3_check_env_example_typer.py` | 8/8 passed |
| pytest (full W6+W11) | 4 test files | 110/110 passed |
| real-repo matrix | `python tools/check_env_example.py --matrix` | 11 required secrets missing (FAIL-CLOSED, как и должно) |

## Файлы

- `tools/check_env_example.py` — расширен (CONFIG_DIR fix + class detection + matrix mode)
- `tests/unit/tools/test_w11_p0_3_check_env_example_matrix.py` — 29 tests
- `tests/unit/tools/test_w6_p1_8_phase3_check_env_example_typer.py` — 8 tests (1 обновлён для --json)
- `docs/adr/INDEX.md` — обновлён (128 → 129 ADRs)

## Ссылки

- ADR-0335 — W11 P0-2 unsafe defaults gate
- ADR-0334 — fact-check master state (стратегический анализ)
- ADR-0084 — typer+rich CLI pattern
- W6 P1-8 Phase 3 — оригинальная typer-миграция check_env_example.py
- PROGRESS_LEDGER: `docs/roadmap/PROGRESS_LEDGER.md`
