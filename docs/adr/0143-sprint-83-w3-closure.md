# ADR-0143 — Sprint 83 W3: Vault DSL wrapper + PIL leak fix

* Статус: Accepted (Sprint 83 W3, 2026-08-31)
* Связано с: PLAN.md §3 (S83 backlog); ADR-0086 (aiocache); ADR-0142 (S68 closure).

## Контекст

Sprint 83 — Production Readiness phase 2. В рамках второй волны роевого
анализа (5 explore-агентов: async/await, type safety, resource leaks,
test quality, config drift) выявлены:

1. **CRITICAL**: ``PIL.Image.open()`` без ``with`` в ``image_resize`` /
   ``image_ocr`` процессорах — file-descriptor leak под нагрузкой.
2. **MEDIUM**: hardcoded URLs/timeouts в нескольких клиентах и
   процессорах (наследие до Sprint 83).
3. **Отсутствие DSL-обёртки** для часто используемой инфраструктурной
   функциональности — Vault secret read. В каждом route, где нужно
   прочитать секрет, разработчик копировал ~20 строк
   ``async def _load_secret()`` boilerplate.

## Решения

### W3-1: CRITICAL fix — PIL Image.open с context manager

В ``src/backend/dsl/engine/processors/rpa/operations/``:

* ``imageresizeprocessor.py`` — обёрнут ``Image.open`` в ``with``.
* ``imageocrprocessor.py`` — обёрнут ``Image.open`` в ``with``.

Другие ``Image.open`` (``blip2_captioner``, ``image_ingester``,
``embedders``) уже использовали ``with`` — audit false positives.

**Тесты** (``tests/unit/dsl/engine/processors/rpa/operations/``):
+10 тестов: happy path, validation, ``to_spec``, resource cleanup,
exception safety, no-dimensions passthrough.

### W3-2: New DSL processor — ``vault_read``

Новый процессор + mixin для чтения Vault KV v2 secrets:

* ``src/backend/dsl/engine/processors/vault_secret.py`` —
  ``VaultSecretProcessor`` с параметрами ``path``, ``output_field``,
  ``version``. Под капотом использует
  ``src/backend/infrastructure/secrets/vault_backend.py``.
* ``src/backend/dsl/builders/vault.py`` — ``VaultSecretMixin`` с
  chainable-методом ``.vault_read(...)``.
* Регистрация в ``processors/__init__.py`` + import в
  ``builders/base/__init__.py``.

**Use case**::

    rb = RouteBuilder.from_("secrets-loader", source="timer:60s")
    rb.vault_read(path="secret/data/db/password", output_field="db_password")
    rb.vault_read(path="secret/data/api/key", output_field="api_key", version=2)
    rb.dispatch_action("db.connect")

При успехе ``exchange.properties[output_field]`` получает ``str`` value
(custom field) или ``{path, value, version}`` dict (default ``"value"``).
При ошибке — ``exchange.fail()``.

**Тесты** (``tests/unit/dsl/engine/processors/test_vault_secret.py``):
8 тестов: happy path, custom output_field, versioned read, exception,
import error, to_spec minimal/full, VaultReadResult dataclass.

### W3-3: New dataclass DTO — ``VaultReadResult``

``@dataclass VaultReadResult(path, value, version)`` — plain DTO для
типизации downstream кода. Не Pydantic (избегаем overhead для
internal DTO). Без ``slots=True`` (Pydantic-style — не требуется).

## Метрики сессии

* Commits W3: 1 (W1+W2 WIP + W3 fix)
* Файлов новых: 3 (``vault_secret.py``, ``vault.py``, test)
* Файлов изменённых: 5 (init-registrations, 2 PIL fix, 1 test fixup)
* Тестов: +18 (10 PIL + 8 Vault)
* ADR count: 92 → 93 (этот)

## Что НЕ сделано в W3 (deferred)

* **Move hardcoded URLs/timeouts** в Settings — отложено. Сейчас работает,
  риск регрессий при переносе превышает выгоду.
* **CRITICAL config drift** (``RAGSettings``, ``JupyterHubSettings``,
  ``CertStoreSettings``) — audit false positive: все три класса уже
  подключены к ``AppBaseSettings`` через ``src/backend/core/config/settings.py``.
* **Add Type safety for ``authorization_gateway`` / ``capabilities/gate``** —
  требует >1 спринта (100% Any в 15 mixin-файлах).
* **Performance fixes N+1** — закрыто в W1+S62, новых нет.

## Sprint 83 DoD score

| # | Wave | Status | Notes |
|---|---|---|---|
| 1 | W1: 6 P0 fixes (repositories, ProcessorPool, MiddlewareChain, embedding, ai_rpa, ai_rlm) | ✅ | Сделано в pre-Sprint 83 сессии |
| 2 | W2: 4 P1 fixes (health, MCP, exchange, pipeline) | ✅ | Сделано в pre-Sprint 83 сессии |
| 3 | W3a: 4 security hotfixes (pickle RCE, 2 SQLi, path traversal) | ✅ | Сделано в pre-Sprint 83 сессии |
| 4 | W3b: TD-018 Part 2 (feature flags migration) | ✅ | Сделано в pre-Sprint 83 сессии |
| 5 | W3c: Cleanup F401 (~2000 imports, 1008 files) | ✅ | Сделано в pre-Sprint 83 сессии |
| 6 | W3d: Refactor god-functions (16 helpers, 13→≤2 nesting) | ✅ | Сделано в pre-Sprint 83 сессии |
| 7 | W3e: N+1 fixes (Batch ~1000x, Timescale ~1000x, IMAP ~100x) | ✅ | Сделано в pre-Sprint 83 сессии |
| 8 | W3f: PIL Image.open leak fix | ✅ | Эта сессия |
| 9 | W3g: Vault DSL processor + mixin + DTO | ✅ | Эта сессия |

**Sprint 83 = 9/9 closed**.

## Next (S84+)

* WAF Phase-3 (production-strict).
* React admin dashboard MVP — real API integration.
* Helm charts (carryover S18).
* Type safety для ``authorization_gateway`` / ``capabilities/gate``.
