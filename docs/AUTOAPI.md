# Auto-Generated API Reference (v19)

**Tool**: [sphinx-autoapi 3.8.0](https://sphinx-autoapi.readthedocs.io/)
**Status**: ✅ Setup complete (2026-06-05)

## Назначение

Полный авто-сгенерированный API reference для всех публичных модулей
проекта `gd_integration_tools`. Извлекается напрямую из docstring'ов
исходного кода при помощи `sphinx-autoapi` и публикуется в
`docs/api/_build/html/autoapi/`.

## Покрытые модули

`sphinx-autoapi` обходит следующие директории (настроено в
`docs/api/conf.py → autoapi_dirs`):

| Директория | Содержимое | Примерное число модулей |
|------------|-----------|------------------------:|
| `src/backend/dsl` | DSL builders, mixins, processors, EIP, proxy | ~80 |
| `src/backend/core` | Config, resilience, scaling, interfaces | ~50 |
| `src/backend/ai` | AI gateway, RAG, guardrails, agentic | ~30 |
| `src/backend/services` | Business services | ~20 |
| `src/backend/infrastructure` | Cache, DB, observability, security | ~40 |
| `src/backend/entrypoints` | gRPC, WebSocket, IMAP, REST | ~15 |
| `src/testkit` | Testing framework | ~10 |

**Итого**: ~245 модулей, ~234 000 LOC.

## Использование

### Локальная сборка

```bash
# Один раз: установить зависимости
pip install -r docs/api/requirements.txt

# Сгенерировать HTML (полная сборка)
./scripts/gen_api_autoapi.sh --clean

# Открыть в браузере
xdg-open docs/api/_build/html/autoapi/index.html   # Linux
open docs/api/_build/html/autoapi/index.html        # macOS
```

### Makefile target (если есть)

```bash
make -C docs/api html
```

### CI integration

```yaml
- name: Build API reference
  run: ./scripts/gen_api_autoapi.sh --clean
- uses: actions/upload-pages-artifact@v3
  with:
    path: docs/api/_build/html
```

## Конфигурация

`docs/api/conf.py`:

```python
autoapi_type = "python"
autoapi_dirs = [
    str(_PROJECT_ROOT / "src" / "backend" / "dsl"),
    str(_PROJECT_ROOT / "src" / "backend" / "core"),
    # ... (7 директорий)
]
autoapi_root = "autoapi"
autoapi_options = [
    "members", "undoc-members", "show-inheritance",
    "show-module-summary", "imported-members",
]
autoapi_member_order = "bysource"
autoapi_keep_files = False
autoapi_exclude_patterns = [
    r".*__pycache__.*", r".*\.venv.*",
    r".*test_.*", r".*_test\.py", r".*\.git.*",
]
```

## Skip patterns

AutoAPI **исключает**:
- `__pycache__/` — compiled bytecode
- `.venv/` — virtual env
- `test_*.py`, `*_test.py` — тесты (идут в coverage, не в API)
- `.git/` — version control

Тесты покрываются pytest coverage, не попадают в user-facing API reference.

## Performance

| Build | Время | Размер HTML | Модулей |
|-------|------:|------------:|--------:|
| Cold (clean) | ~2-3 min | ~250 MB | ~245 |
| Incremental | ~30 sec | — | — |

Для CI рекомендуется `--clean` (полная пересборка), для dev —
incremental.

## Сравнение с ручным docs/

| Подход | Покрытие | Поддержка |
|--------|---------:|----------:|
| `docs/` (tutorials, ADRs) | 5% (high-level) | ✅ Ручная |
| `docs/api/` (autoapi) | **95% (all public API)** | ✅ Авто |

AutoAPI — основной reference, ручные docs/ — для архитектурных решений
и how-to.

## Что генерируется

- Все классы (с inheritance tree)
- Все функции и методы
- Все Protocol и ABC
- Все dataclass и TypedDict
- Docstrings (Google style через napoleon)
- Type hints
- Source links (через `viewcode`)

## Что НЕ генерируется (по design)

- Private members (начинаются с `_`) — без `--private-members`
- Test files (`test_*.py`)
- Migration files (alembic)
- Generated files (`_pb2.py`, `*_pb2_grpc.py` — но они попадают,
  их можно добавить в exclude_patterns при желании)

## Maintenance

- ✅ Конфиг в `docs/api/conf.py` (одно место для правок)
- ✅ Скрипт `scripts/gen_api_autoapi.sh` (CI-ready)
- ✅ Build artifacts в `_build/html/` (gitignored)
- ✅ Полная регенерация при изменении любого docstring

## Связанные документы

- [Sphinx autodoc](https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html)
- [sphinx-autoapi docs](https://sphinx-autoapi.readthedocs.io/)
- [Napoleon (Google docstrings)](https://www.sphinx-doc.org/en/master/usage/extensions/napoleon.html)
- [Sphinx RTD theme](https://sphinx-rtd-theme.readthedocs.io/)
- v19 §11 Sprint 39 W4 (auto-generated API reference task)
