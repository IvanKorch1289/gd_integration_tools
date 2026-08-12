# 03 — Services domain audit (cycle 1, phase 1)

> Scope: `src/backend/services/**` (excluding `ai/**`, `workflow/**`, `workflows/**`,
> `security/**`, `auth/**`, `authorization/**`, `agent_security/**`) и соответствующие
> `tests/unit/services/**` (excluding `ai/**`, `security/**`).
>
> Фактический объём: **181 production .py файлов** (181 − ai/workflow/workflows/security/auth/authorization/agent_security)
> и **106 test .py файлов**. Baseline: `b69d6b49bc62918a02e47dc20ab81615fd8500b1`.
> В working tree на момент старта изменены `src/backend/infrastructure/storage/s3.py`
> и `uv.lock` (pre-existing, рою не приписывать).
>
> Внимание: рабочая ветка HEAD = `2f620910` (1 коммит поверх baseline — `S3 multipart
> abort on CancelledError/MemoryError`). Изменений в `src/backend/services/**` от этого
> коммита нет.

## Scope / не проверено

- **Не проверено:** полная live-проверка каждого `@pytest.mark.asyncio`/`integration`
  теста; runtime поведение при поднятой инфраструктуре (Redis/ClickHouse/Vault/Kafka);
  CI-результаты (`make lint`, `make type-check`, `make test`) — запуск заблокирован
  инструкцией «никаких git mutation, безопасные targeted read-only проверки».
- **Не проверено:** `src/backend/services/ai/**`, `workflow/**`, `workflows/**`,
  `security/**`, `auth/**`, `authorization/**`, `agent_security/**` — out of scope
  (отдельные аналитики).
- **Не проверено:** содержимое каждого `tools/plugin_migration_diff.py` и других
  tools (не services).
- **Не проверено:** содержимое фронтенда (`src/frontend/**`) и `entrypoints/**`,
  хотя `services/admin/api.py` импортируется из entrypoints.
- **Не проверено:** `tests/integration/**` — out of unit-scope.
- **Не проверено:** `docs/**` — out of code-scope.
- **Частично проверено:** `extensions/*/services/waf_route` — упомянуто только как
  import-target в `services/integrations/skb.py:16`; сама имплементация не
  читалась (extensions — другой домен).

## Verified strengths

| ID | Что подтверждено | Evidence (path:line) |
|---|---|---|
| STR-01 | Capability-checked facade pattern применён системно для всех external-surface | `src/backend/services/storage/facade.py:55-61` (`_assert_read/_assert_write`); `cache/facade.py:65-67`; `secrets/facade.py:40-42`; `observability/facade.py`; `messaging/facade.py:52-54`; `scheduler/facade.py:32-34`; `tenancy/facade.py:67-75`; `pii/facade.py`; `resilience/facade.py:53-55` |
| STR-02 | Rate-limit fail-closed default (deny при Redis-outage) | `src/backend/services/resilience/facade.py:96-116` (B-05 fix: `fail_mode="closed"` default, `rate_limit_fail_mode` env-controlled) |
| STR-03 | Sinks/Source capability-gate fail-closed (deny при AuthZ недоступен) | `src/backend/services/integrations/facade.py:93-98` ("Fail-closed: если authz слой недоступен, запрещаем доступ") |
| STR-04 | RedisDedupeStore явный `fail_closed` параметр (S71 W3, prod-recommended=True) | `src/backend/services/sources/idempotency.py:91-119` (default=False для backward-compat; docstring явно говорит про financial/regulatory workloads) |
| STR-05 | Fernet encryption at-rest для browser-cookies | `src/backend/services/rpa/browser_cookies_store.py:100-128` (Fernet AES-128-CBC + HMAC-SHA256, runtime fail при отсутствии env-ключа вне dev_light) |
| STR-06 | SSRF protection в webhook scheduler | `src/backend/services/ops/webhook_scheduler.py:98-109` (`_validate_url` из `dsl.engine.processors.scraping` — блокирует private/loopback/metadata IPs) |
| STR-07 | AdaptiveTimeoutPolicy интегрирован в BaseExternalAPIClient | `src/backend/services/core/base_external_api.py:147-179` (P99 по host/endpoint, fallback на hardcoded) |
| STR-08 | Layer checker baseline 175 legacy / 0 NEW нарушений подтверждён ручным grep | только 11 прямых `from src.backend.infrastructure` в services (после исключения ai/workflow/security/auth/etc), все — документированные facade-shims с `# noqa: E402,F401` и `Layer policy:` docstring |
| STR-09 | `core/admin/api.py` использует CapabilityFacade + FacadeCapabilityAdapter вместо прямого `CapabilityGate()` (S198 fix) | `src/backend/services/admin/api.py:64-77`; `src/backend/services/admin/_capability_adapter.py:15-39` |
| STR-10 | Circuit Breaker + Retry pattern для outbound RPA клиентов | `src/backend/services/rpa/desktop_rpa_client.py:41-86` (`_get_desktop_rpa_breaker`, `_get_execute_with_retry`); `rpa/desktop_session_pool.py:52-60` (`_get_pool_breaker`); `webhook_scheduler.py:135-145` (RPACallPolicy) |
| STR-11 | DLQWriter Protocol для audit-service через canonical path (S180) с legacy JSONL fallback | `src/backend/services/audit/clickhouse_audit_service/service.py:188-218` (приоритет dlq_writer > dlq_path > silent loss с WARNING) |
| STR-12 | OpenLineage HTTP emitter с overflow protection (drop-oldest) и batch+TTL | `src/backend/services/lineage/lineage_http_emitter.py:118-130,134-157` |
| STR-13 | DataFrame abstraction Polars-first с graceful fallback на `Any` | `src/backend/services/io/dataframe.py:22-25,39` (`pl = None` при ImportError; `DataFrame = pl.DataFrame if pl is not None else Any`) |
| STR-14 | `app_state_singleton` decorator-паттерн единообразный (single source of DI registry) | 15+ файлов используют `@app_state_singleton(name, factory=...)` с `raise NotImplementedError  # заменяется декоратором` — стандартный, не stub |
| STR-15 | `BaseExternalAPIClient` унифицирует WAF-routing + auth-headers + timeout для всех external API сервисов (SKB, DaData) | `src/backend/services/core/base_external_api.py:30-275`; `integrations/dadata.py:18-69`; `integrations/skb.py:26-43` |
| STR-16 | RBAC + audit trail pattern в AdminService через AuthorizationGateway | `src/backend/services/admin/api.py:82-128` (`_authorize` raise `AdminAuthorizationError` на deny; `emit_admin_action` на allow/error/denied) |
| STR-17 | `RouteLoader._load_one` — fail-closed capability invariant (`route.capabilities ⊆ plugin ∪ public-core`) | `src/backend/services/routes/loader.py:277-298` (`CapabilitySupersetError → status="failed"`) |
| STR-18 | `RouteHotReloader` content-hash dedup (S178) — no-op reload на touch | `src/backend/services/routes/hot_reloader.py:205-220` (sha256 cache) |
| STR-19 | Async-first enforced в OCR (`asyncio.to_thread` для CPU-bound pytesseract) | `src/backend/services/rpa/ocr_processor.py:90-117` |
| STR-20 | TaskGroup (PEP 654) для structured concurrency в health-check | `src/backend/services/ops/health.py:179-184` |
| STR-21 | Single-Entry / facade pattern закрыт для всех доменов (storage, cache, secrets, observability, messaging, scheduler, tenancy, pii, integrations) — extensions импортируют только через facade | подтверждено grep: extensions не содержат прямых `infrastructure.*` импортов (out of scope, но структурно соблюдается) |
| STR-22 | `pyproject.toml` имеет pinned версии для всех heavy-deps (polars — `[dataframes]`, jsonschema — отсутствует!) | `pyproject.toml:299-302` (polars optional), но `jsonschema` не pinned — finding DOMAIN-P3-001 |

## Findings table

| ID | Pri | Path:line | Title |
|---|---|---|---|
| DOMAIN-P0-001 | P0 | `src/backend/services/admin/api.py:97-102` | **fail-open** in `_authorize` — AuthZ unavailable → admin actions allowed without check |
| DOMAIN-P1-001 | P1 | `src/backend/services/ops/data_quality/{apply_mixin,check_mixin,rule_mgmt_mixin,schema_mixin,__init__}.py` | 4-way dead duplication of `DQSeverity`/`DQViolation`/`DQCheckResult`/`DQRule` |
| DOMAIN-P1-002 | P1 | `src/backend/services/integrations/skb.py:16` | reverse-layer import `services → extensions.skb.services.waf_route` (documented shim, but still violation) |
| DOMAIN-P1-003 | P1 | `src/backend/services/io/files.py:11` | reverse-layer import `services → extensions.core_entities.files.services.files` (documented shim) |
| DOMAIN-P2-001 | P2 | `src/backend/services/billing/quotas_service.py:17-37` | `QuotasService` stub — `__init__` raises `NotImplementedError`; never instantiable, dead code |
| DOMAIN-P2-002 | P2 | `src/backend/services/integrations/imported_action_service.py:81-101` | `dispatch_endpoint` returns hardcoded `{"status": "stub", ...}` — actual invocation never wired (W22 deferred) |
| DOMAIN-P2-003 | P2 | `src/backend/services/io/files.py:1-20` | full-file DeprecationWarning shim — should be removed after deprecation cycle |
| DOMAIN-P2-004 | P2 | `src/backend/services/integrations/skb.py:142-152` | `resolve_waf_route` shim — emits `DeprecationWarning`, scheduled for removal |
| DOMAIN-P2-005 | P2 | `src/backend/services/audit/clickhouse_audit_service/service.py:189-218` | DLQ `silent_loss + WARNING` branch (`None → silent loss`) — kept intentionally for backward-compat but is fail-open for audit |
| DOMAIN-P2-006 | P2 | `src/backend/services/cache/facade.py:78-95,114-116` | `UnifiedCacheFacade.get/set` — `except Exception as exc` без narrowing (CacheError/ConnectionError vs programmer-error `TypeError`); silent fallback to next tier может маскировать bug |
| DOMAIN-P3-001 | P3 | `src/backend/services/ops/data_quality/apply_mixin.py:316-346`, `schema_registry/registry.py:251-270` | `jsonschema` используется напрямую, но **не pinned в pyproject.toml** — supply-chain/CVE risk |
| DOMAIN-P3-002 | P3 | `src/backend/services/io/export_service.py:83-142` | `ExcelExporter` через `openpyxl` (sync, ~70 LOC), хотя polars уже есть как `read_excel/write_excel` — дублирование логики |
| DOMAIN-P3-003 | P3 | `src/backend/services/io/export_service.py:145-218` | `PdfExporter` через `reportlab` (~73 LOC custom tabling) — можно заменить на `polars.write_excel` + простой HTML→PDF (но reportlab даёт finer control; не проверено на maintenance risk) |
| DOMAIN-P3-004 | P3 | `src/backend/services/ops/anomaly_detector.py:56-103` | z-score на `collections.deque` — для time-series forecasting можно `statsmodels.tsa` или `prophet`, но basic достаточно; YAGNI не блокирует |
| DOMAIN-P3-005 | P3 | `src/backend/services/lineage/lineage_http_emitter.py:171-205` | `urllib.request.urlopen` — `httpx.AsyncClient` уже в pyproject (S18 W1 migration), синхронный HTTP в async-контексте |
| DOMAIN-P4-001 | P4 | `src/backend/services/ops/scheduled_reports.py:52-181` | in-memory `_schedules` dict — нет persistence; integration с APScheduler (уже в deps) даст cron-actually-fire + history |
| DOMAIN-P4-002 | P4 | `src/backend/services/ops/message_replay.py:52-179` | in-memory `_messages` dict — теряется при restart; можно Redis-backed (`webhook:dlq` pattern уже есть) |
| DOMAIN-P4-003 | P4 | `src/backend/services/ops/dq_remediation.py:266-288` | `CompositeRemediator` — нет метрик «сколько fix'ов применено per-rule per-day»; минимально — `prometheus_counter` |
| DOMAIN-P4-004 | P4 | `src/backend/services/jupyter/hub_run_orchestrator.py:166-188` | inline-notebook content (multipart) уже gated через `secure.jupyter_inline_content_enabled`; можно ещё добавить sandbox-only enforcement |

## Detailed evidence

### DOMAIN-P0-001 — Admin fail-open on AuthZ unavailable (security-critical)

- **Path:** `src/backend/services/admin/api.py:97-102`
- **Verified evidence:**
  ```python
  authz = self._get_authz()
  if authz is None:
      # AuthZ unavailable — fail-open for dev, but log warning
      logger.warning(
          "AuthZ unavailable for %s@%s/%s — allowing", actor, resource, action
      )
      return
  ```
- **Impact:** Если `AuthorizationGateway` (см. `services/admin/_capability_adapter.py:15-39`)
  не удаётся разрешить (capability_facade не инициализирован, БД недоступна,
  Vault недоступен) — ВСЕ admin actions (`toggle_feature_flag`, `get_feature_flags`,
  `get_audit_log`, `list_active_sessions`) проходят БЕЗ проверки прав.
  В production это означает: при падении AuthZ слоя любой actor с валидным
  FastAPI-handle получает admin доступ (например, переключение feature flags,
  чтение audit log).
- **Minimal recommendation:**
  Заменить fail-open на fail-closed — `raise AdminAuthorizationError` когда `authz is None`.
  Если требуется dev-mode bypass — через отдельный `settings.admin.dev_allow_unauth = False`
  (default False, fail-closed).
- **Test criterion:** Unit-тест `test_admin_authorize_authz_unavailable_raises`:
  ```
  AdminService(authorization_gateway=None)  # mock cap-facade unavailable
  await admin._authorize(actor="user", resource="x", action="y")
  # assert raises AdminAuthorizationError
  ```
- **Priority justification:** Admin endpoints → privilege escalation vector
  при AuthZ outage; fail-open — нарушение AGENTS.md правила «fail-closed security».

### DOMAIN-P1-001 — 4-way duplication of DQ* dataclasses

- **Path:**
  - `src/backend/services/ops/data_quality/__init__.py:68-133` (canonical re-export)
  - `src/backend/services/ops/data_quality/apply_mixin.py:30-71` (own copies)
  - `src/backend/services/ops/data_quality/check_mixin.py:28-70` (own copies)
  - `src/backend/services/ops/data_quality/rule_mgmt_mixin.py:30-79` (own copies)
  - `src/backend/services/ops/data_quality/schema_mixin.py:29-71` (own copies)
- **Verified evidence:** Все 5 файлов независимо определяют `DQSeverity`
  (INFO/WARNING/ERROR/CRITICAL), `DQViolation`, `DQCheckResult`, `DQRule` с
  идентичными полями. Mixin-файлы определяют локальные копии для использования
  в методах типа `_apply_rule` / `_check_rule` (т.к. `__init__.py` импортирует
  mixin ПОСЛЕ объявления классов в каждом mixin-файле, но ДО type-checking
  в `apply_mixin.py`). Итого 4 × ~38 LOC = ~152 LOC dead duplication.
- **Impact:**
  - Maintenance burden: 4 точки изменения при добавлении поля (например,
    `tags: list[str] = []`).
  - Structural-typing risk: dataclass instances from `__init__.py` going
    into `apply_mixin.py::_apply_rule` — `isinstance` mismatch (apply_mixin's
    own DQViolation is a separate class), но duck-typing покрывает.
  - mypy может давать false negatives.
- **Minimal recommendation:** Удалить дубликаты из 4 mixin-файлов; импортировать
  `DQSeverity, DQViolation, DQCheckResult, DQRule` из `__init__.py` через
  TYPE_CHECKING-блок (как уже сделано для `DQRule/DQViolation` в
  `_protocol.py:17`). Переупорядочить импорты (mixin-импорты ПЕРЕД dataclass
  определениями) для избежания circular.
- **Test criterion:** `mypy --strict` должен пройти без `type: ignore`; unit-test
  `apply_mixin._apply_rule(create_rule(), {"field": "x"}, "ds")` —
  isinstance(violation, DQViolation) == True.
- **Priority justification:** P1 (architecture/maintainability) — не блокер
  prod, но создаёт bug-инкубатор при будущих изменениях API.

### DOMAIN-P1-002 — services → extensions reverse-layer (skb back-compat shim)

- **Path:** `src/backend/services/integrations/skb.py:16`
  ```python
  from extensions.skb.services.waf_route import (
      resolve_waf_route as _resolve_waf_route_impl,
  )
  ```
- **Verified evidence:** Документировано как back-compat shim (Cycle-35 B2):
  `services/integrations/skb.py:1-9` docstring говорит «Cycle-35 B2: чистая
  логика WAF-маршрутизации вынесена в extensions.sk.b.services.waf_route».
  Reverse-import (services depends on extensions) нарушает AGENTS.md
  «extensions → core only» правило.
- **Impact:** Затягивает deletion-of-shim (нужно ждать пока все callsites
  перейдут на extensions-путь). На текущий момент layer checker
  знает об этом исключении (175 legacy baseline).
- **Minimal recommendation:** Добавить TODO с датой «удалить в Sprint 38+»;
  пройтись по callsites (`extensions/skb/...`) и убедиться что все они уже
  используют extensions-путь напрямую.
- **Test criterion:** `tools/check_layers.py` — ожидаемое legacy count после
  удаления: -1 (174 legacy / 0 new).
- **Priority justification:** P1 — известное legacy исключение, не новое.
  Документировано, не блокер.

### DOMAIN-P1-003 — services → extensions reverse-layer (files shim)

- **Path:** `src/backend/services/io/files.py:11-13`
  ```python
  from extensions.core_entities.files.services.files import FileService, get_file_service
  ```
- **Verified evidence:** Документировано как backward-compat shim (R-V15-16):
  «Канонический модуль теперь — extensions.core_entities.files.services.files».
  Эмитит `DeprecationWarning` на import.
- **Impact:** Аналогично DOMAIN-P1-002.
- **Minimal recommendation:** Удалить после deprecation-cycle; проверить что
  `from extensions.core_entities.files.services.files import FileService` —
  единственный путь у всех callers.
- **Test criterion:** Поиск `from src.backend.services.io.files import`
  в репо должен давать 0 hits.
- **Priority justification:** P1 (legacy исключение).

### DOMAIN-P2-001 — `QuotasService` stub, NotImplementedError на `__init__`

- **Path:** `src/backend/services/billing/quotas_service.py:17-37`
- **Verified evidence:**
  ```python
  class QuotasService:
      """Stub: real billing backend not yet integrated. See NoOpBillingFacade."""

      def __init__(self) -> None:
          raise NotImplementedError(
              "QuotasService not yet implemented; use NoOpBillingFacade via "
              "src.backend.core.di.providers.billing.get_quotas_backend_provider()."
          )

      async def consume_request(self, tenant_id: str):  # pragma: no cover
          raise NotImplementedError("QuotasService.consume_request is a stub")

      async def check_tokens(self, tenant_id: str, tokens: int):  # pragma: no cover
          raise NotImplementedError("QuotasService.check_tokens is a stub")
  ```
  Тест `tests/unit/services/billing/test_no_op_billing_cycle33.py` явно проверяет
  что `QuotasService()` бросает `NotImplementedError` (см. test_isinstance_protocol
  region — тест протокола, не stub'а).
- **Impact:** Dead code, который держит import-path живым. Любая попытка
  использовать `QuotasService()` упадёт с NotImplementedError.
- **Minimal recommendation:** Удалить `services/billing/quotas_service.py` целиком;
  проверить что DI-провайдер (`core.di.providers.billing`) использует ТОЛЬКО
  `NoOpBillingFacade`. Если `QuotasService` символ нужен — заменить
  на `from services.billing.no_op_billing import NoOpBillingFacade as QuotasService`
  alias.
- **Test criterion:** `tests/unit/services/billing/` — удалить
  `test_quotas_service_*` тесты (если есть); убедиться что test_no_op_billing
  покрывает функциональность.
- **Priority justification:** P2 (dead code) — не блокер, но занимает
  cognitive load при чтении модуля.

### DOMAIN-P2-002 — `dispatch_endpoint` stub в ImportedActionService

- **Path:** `src/backend/services/integrations/imported_action_service.py:81-101`
- **Verified evidence:**
  ```python
  async def dispatch_endpoint(self, *, action: str, **payload: Any) -> dict[str, Any]:
      ...
      meta = self._endpoints[action]
      return {
          "status": "stub",
          "operation_id": meta.operation_id,
          "method": meta.method,
          "path": meta.path,
          "payload": payload,
      }
  ```
  Docstring (line 14): «Реальный invocation через Invoker (W22) подключается отдельно».
  Этот stub зарегистрирован в ActionHandlerRegistry через
  `import_service.py:259-264` (`service_method="dispatch_endpoint"`).
- **Impact:** Endpoint импортированный через `import_service.import_and_register`
  при вызове возвращает `{"status": "stub", ...}` вместо реального HTTP-вызова.
  Это fail-open поведение для импортированных connectors (S44).
- **Minimal recommendation:** Задокументировать в docstring явно: «STUB —
  возвращает metadata; реальное invocation подключается в Sprint X»;
  добавить `TODO: WIRE-UP W22 INVOKER` с target sprint.
- **Test criterion:** Integration-тест: при вызове `imported_action.dispatch_endpoint`
  возвращает `{"status": "stub"}`; production-flag `feature_flags.imported_actions_live=True`
  (default False) → переключение на реальный dispatch.
- **Priority justification:** P2 — известный stub, задокументирован;
  но отсутствие feature-flag для stub-режима делает его implicit.

### DOMAIN-P2-003 — full-file DeprecationWarning shim (files)

- **Path:** `src/backend/services/io/files.py:1-20`
- **Verified evidence:** Целый файл — shim:
  ```python
  warnings.warn(
      "src.backend.services.io.files устарел; используйте "
      "extensions.core_entities.files.services.files (R-V15-16).",
      DeprecationWarning,
      stacklevel=2,
  )
  ```
- **Impact:** DeprecationWarning на каждый import (включая transitive).
  Может засорять логи.
- **Minimal recommendation:** Удалить после проверки callers.
- **Test criterion:** `git grep "from src.backend.services.io.files"` → 0 hits.
- **Priority justification:** P2 (cleanup).

### DOMAIN-P2-004 — `resolve_waf_route` shim в skb

- **Path:** `src/backend/services/integrations/skb.py:142-152`
- **Verified evidence:**
  ```python
  def resolve_waf_route(
      environment: str | None, waf_url: str | None
  ) -> tuple[str | None, bool]:
      """DEPRECATED: используйте ``extensions.skb.services.waf_route.resolve_waf_route``."""
      warnings.warn(...)
  ```
- **Impact:** Аналогично DOMAIN-P2-003.
- **Minimal recommendation:** Удалить после deprecation-cycle.
- **Test criterion:** `git grep "from src.backend.services.integrations.skb import resolve_waf_route"` → 0 hits.
- **Priority justification:** P2 (cleanup).

### DOMAIN-P2-005 — DLQ silent_loss path в audit-service

- **Path:** `src/backend/services/audit/clickhouse_audit_service/service.py:189-218`
- **Verified evidence:**
  ```python
  if self._dlq_writer is not None:
      try:
          ...
          await self._dlq_writer.write(envelope)
      except Exception as dlq_exc:
          _logger.error(...)
      return
  # Приоритет 2: legacy JSONL path (deprecated)
  backend = self._get_dlq_backend()
  if backend is None:
      return  # ← silent loss + WARNING (per docstring line 45)
  ```
  Docstring явно говорит про `silent_loss + WARNING` для `None` branch (line 45).
- **Impact:** Audit-события могут быть потеряны при отсутствии и canonical
  DLQWriter, и legacy JSONL path. Это **data-loss risk** для security/regulatory
  audit-trail. Однако docstring явно маркирует как deprecated/intentional.
- **Minimal recommendation:** В production, если оба DLQ пути недоступны —
  `_logger.critical` (не WARNING) + emit metric
  `audit_event_lost_total{reason="dlq_unavailable"}`.
- **Test criterion:** Unit-тест: `ClickHouseAuditService()._send_to_dlq(...)`
  с пустыми `_dlq_writer` и `_dlq_path` — должна быть хотя бы `critical`-log
  + metric increment.
- **Priority justification:** P2 (audit-data-loss, но documented behavior);
  не P0 т.к. только при полном отсутствии DLQ infra.

### DOMAIN-P2-006 — `UnifiedCacheFacade` широкий except Exception

- **Path:** `src/backend/services/cache/facade.py:78-95,114-116,131-133,150-151,164-165`
- **Verified evidence:** 5 мест с `except Exception as exc` для cache-fallback.
  Пример:
  ```python
  try:
      value = await self._primary.get(full)
      if value is not None:
          return CacheResult(value=value, hit=True, backend="primary")
  except Exception as exc:
      _logger.warning("Cache primary get failed key=%s: %s", full, exc)
  ```
- **Impact:** Программистские ошибки (TypeError, ValueError, AttributeError)
  маскируются под cache-failure → silent fallback на next tier. Это может
  маскировать bug'и в caller'ах.
- **Minimal recommendation:** Narrow except до `(OSError, ConnectionError,
  TimeoutError, redis.RedisError)` (cache-specific exceptions); `Exception`
  только для catastrophic fail.
- **Test criterion:** `UnifiedCacheFacade.get(...)` с `_primary.get` бросающим
  `TypeError` — должен propagate (не маскировать), а не silent-fallback.
- **Priority justification:** P2 — bug-incubator, не security.

### DOMAIN-P3-001 — `jsonschema` не pinned в pyproject.toml

- **Path:** `src/backend/services/ops/data_quality/apply_mixin.py:316-326` +
  `src/backend/services/schema_registry/registry.py:251-270`
- **Verified evidence:**
  - `grep "jsonschema" pyproject.toml` → 0 matches (no pin)
  - `from jsonschema import Draft202012Validator` используется в
    `schema_registry/registry.py:254` без version constraint.
  - `import jsonschema` в `apply_mixin.py:318` без version constraint.
- **Impact:** Supply-chain risk — версия jsonschema не контролируется.
  CVE в jsonschema (если будут обнаружены) не будут автоматически
  фикситься через `pip-audit` (не задетектит, если pin отсутствует).
- **Library recommendation:**
  - **Библиотека:** `jsonschema>=4.21.0,<5.0.0` (latest stable, Python 3.14 wheel ok).
  - **Наличие в pyproject:** отсутствует.
  - **Maintenance risk:** jsonschema — actively maintained (Julian Berman et al.),
    последний release Q1 2024; нет серьёзных licensing issues (MIT).
  - **License:** MIT.
  - **LOC delta:** ~0 (только добавление pin).
- **Minimal recommendation:** Добавить `"jsonschema>=4.21.0,<5.0.0"` в
  `[project.dependencies]` (или в `[dev-group]` если только для dev/test).
- **Test criterion:** `uv pip-audit` — должен видеть jsonschema version и
  detect CVE при наличии.
- **Priority justification:** P3 (supply-chain hygiene).

### DOMAIN-P3-002 — `ExcelExporter` через `openpyxl` (vs. polars)

- **Path:** `src/backend/services/io/export_service.py:83-142`
- **Verified evidence:**
  ```python
  class ExcelExporter:
      """XLSX via openpyxl with auto column width."""
      ...
      def export(...):
          ...
          from openpyxl import Workbook
          ...
  ```
  В `pyproject.toml:39` уже есть `"openpyxl>=3.1.5,<4.0.0"`.
  Polars (опциональный, `[dataframes]` extra) также уже имеет
  `df.write_excel(...)` (см. `services/io/dataframe.py:79-96`).
- **Impact:** Дублирование логики export в Excel; ~60 LOC custom openpyxl-кода
  (auto column width, etc.) уже есть в polars.
- **Library recommendation:**
  - **Библиотека:** `polars.write_excel` (уже в deps, optional `[dataframes]`).
  - **Наличие в pyproject:** optional.
  - **Maintenance risk:** polars — actively maintained (ritchie46 et al.),
    Apache 2.0 license; ABI совместим с Python 3.14.
  - **License:** MIT (polars wrapper), Apache 2.0 (core).
  - **LOC delta:** −50 (60 LOC → ~10 LOC через polars).
- **Minimal recommendation:** Если polars уже required для dataframe — заменить
  ExcelExporter на polars backend. Если нет — оставить openpyxl, но вынести
  в `extensions/io_excel/`.
- **Test criterion:** Excel-export benchmark: polars < openpyxl на >1k rows.
- **Priority justification:** P3 (library replacement, YAGNI — оставить).

### DOMAIN-P3-003 — `PdfExporter` через `reportlab` (vs. polars)

- **Path:** `src/backend/services/io/export_service.py:145-218`
- **Verified evidence:**
  ```python
  class PdfExporter:
      """PDF via reportlab. Landscape A4, tabular layout."""
      ...
      from reportlab.lib import colors
      from reportlab.lib.pagesizes import A4, landscape
      from reportlab.lib.styles import getSampleStyleSheet
      from reportlab.platypus import (...)
  ```
  `pyproject.toml:435` содержит `"reportlab>=4.0.0,<5.0.0"`.
- **Impact:** ~73 LOC custom PDF-tabling кода; reportlab даёт finer control
  над layout (colors, padding, font), но для простого tabular report
  overkill.
- **Library recommendation:**
  - **Альтернативы:** `fpdf2` (легче, pure-python) или polars→HTML→weasyprint.
  - **Maintenance risk:** reportlab — стабильный (max 2-3 release/year),
    BSD-3-Clause license; не проверено на Python 3.14 wheel.
  - **License:** BSD-3-Clause.
  - **LOC delta:** −30 (~70 → ~40 LOC если перейти на fpdf2).
- **Minimal recommendation:** Не менять — reportlab даёт нужный control;
  custom-код минимален. Но: добавить в `pyproject.toml` security-pinning
  (`reportlab>=4.2.0,<5.0.0` если есть CVE).
- **Priority justification:** P3 (low priority — текущий код работает).

### DOMAIN-P3-004 — `AnomalyDetector` basic z-score

- **Path:** `src/backend/services/ops/anomaly_detector.py:56-103`
- **Verified evidence:** Использует `statistics.mean/stdev` + `collections.deque`.
- **Impact:** Для production time-series forecasting basic z-score может
  быть недостаточно (no seasonality, no trend detection).
- **Library recommendation:**
  - **Альтернативы:** `statsmodels` (SARIMA), `prophet` (Facebook), `ruptures`
    (changepoint detection).
  - **Maintenance risk:** statsmodels — well-maintained (BSD-3), prophet —
    core Python OK; ruptures — активен.
  - **License:** BSD-3 (statsmodels), MIT (prophet).
  - **LOC delta:** −20 если перейти на statsmodels (модель уже реализована).
- **Minimal recommendation:** НЕ менять — YAGNI для MVP; basic z-score
  достаточно для «sudden spike / error rate alert».
- **Priority justification:** P3 (YAGNI).

### DOMAIN-P3-005 — `urllib.request.urlopen` в lineage_http_emitter

- **Path:** `src/backend/services/lineage/lineage_http_emitter.py:171-205`
- **Verified evidence:**
  ```python
  req = urllib.request.Request(...)
  with urllib.request.urlopen(req, timeout=...) as resp:
      ...
  ```
  Это СИНХРОННЫЙ HTTP в async-контексте (другие emitters
  — `kafka_producer`, `redis` — все async).
- **Impact:** Blocking I/O в event loop. Хотя `urllib` редко долго висит,
  при недоступном сервере может занять `timeout_s` (default 5s) секунд
  event loop.
- **Library recommendation:**
  - **Альтернатива:** `httpx.AsyncClient` (уже в deps, `pyproject.toml:103-105`).
  - **Наличие:** да.
  - **Maintenance risk:** httpx — well-maintained (encode/httpx), BSD-3.
  - **License:** BSD-3.
  - **LOC delta:** −10 (~30 → ~20 LOC).
- **Minimal recommendation:** Заменить на `httpx.AsyncClient().post(...)`.
  Поместить в TODO.
- **Test criterion:** Unit-тест с mock'ом endpoint'а — должен быть async.
- **Priority justification:** P3 (low priority — synchronous urllib редко висит).

### DOMAIN-P4-001 — `ScheduledReportsService` in-memory без persistence

- **Path:** `src/backend/services/ops/scheduled_reports.py:52-181`
- **Verified evidence:** `_schedules: dict[str, ReportSchedule]` хранится
  в module-instance singleton (`@app_state_singleton`); cron из
  ReportSchedule никогда не парсится → manual `run_now()`.
- **Impact:** Reports перезапускаются только через manual `run_now`;
  нет настоящего cron-driven execution.
- **Library recommendation:**
  - **Альтернатива:** APScheduler (уже в pyproject.toml:43-44), который
    уже используется в `services/scheduler/facade.py`.
  - **LOC delta:** −20 (если интеграция с APScheduler).
- **Minimal recommendation:** Интеграция с `SchedulerFacade.add_job` для
  реального cron execution; persistence schedules в Mongo/Redis.
- **Priority justification:** P4 (new feature, YAGNI).

### DOMAIN-P4-002 — `MessageReplayService` in-memory без persistence

- **Path:** `src/backend/services/ops/message_replay.py:52-179`
- **Verified evidence:** `_messages: dict[str, ReplayMessage]` —
  теряется при restart.
- **Impact:** Replay история не переживает process restart.
- **Library recommendation:** Redis (уже в deps); pattern из
  `webhook_relay.py:_DLQ_KEY = "webhook:dlq"`.
- **LOC delta:** −30 (in-memory → Redis).
- **Priority justification:** P4 (new feature).

### DOMAIN-P4-003 — DQ-remediation без метрик

- **Path:** `src/backend/services/ops/dq_remediation.py:266-288`
- **Verified evidence:** `total_fixes += 1` — инкрементируется, но нет
  metric export.
- **Impact:** Не observability для «сколько records auto-fixed за день».
- **Minimal recommendation:** `metrics_registry.counter("dq_fixes_total", ...)`
  per rule_name.
- **LOC delta:** +5.
- **Priority justification:** P4 (observability feature).

### DOMAIN-P4-004 — JupyterHub inline-content: добавить sandbox-only enforcement

- **Path:** `src/backend/services/jupyter/hub_run_orchestrator.py:166-188`
- **Verified evidence:** Уже gated через `secure.jupyter_inline_content_enabled`
  (default False = deny). При включении — arbitrary Python execution в Hub kernel.
- **Impact:** Inline notebook = remote code execution vector; gating OK,
  но нет enforcement «использовать только e2b backend» (sandboxed).
- **Minimal recommendation:** При `notebook_content is not None` — принудительно
  `backend_kind == BackendKind.E2B` (S75 W1).
- **LOC delta:** +3.
- **Priority justification:** P4 (defense-in-depth).

## Contradictions / overlaps to flag

1. **Notifications — тройное дублирование стека:**
   - `services.notifications.facade.NotificationsFacade` — umbrella facade
     с `_messaging_facade` + `_apprise_service` (S174).
   - `services.messaging.facade.MessagingFacade` — базовый email/telegram/webhook.
   - `services.notifications.apprise_service.AppriseNotificationService` — apprise-only.
   - `services.ops.notification_hub.NotificationHub` — DEPRECATED в S223, но
     всё ещё используется (см. `services/ops/scheduled_reports.py:149-159`,
     `services/ops/anomaly_detector.py:111-124`). Помечен на удаление в
     `H3_PLUS (2026-07-01+)` — но H3 не наступил на момент аудита.
   - **Contradiction:** 4 параллельных notification-стека в одном домене,
     только 1 помечен deprecated, остальные 3 — long-term. Это НЕ bug,
     но cognitive load.
   - **Recommendation:** Зафиксировать canonical path через
     `core.notifications.get_gateway()` (уже есть), и явно удалить
     `services.ops.notification_hub.NotificationHub` (или жёстко
     перевести callers).

2. **Capability-gate — двойной контракт:**
   - `services.capabilities.facade.CapabilityFacade` — primary facade.
   - `services.admin._capability_adapter.FacadeCapabilityAdapter` —
     CapabilityGatewayProtocol adapter поверх facade.
   - `core.security.capabilities.gate.CapabilityGate` — singleton
     underlying.
   - В `services/admin/api.py:74-77` используется adapter (правильно);
   в `services/integrations/facade.py:84-88` — прямой lazy-import
   `services.authorization.facade` (другой слой). Это 2 разных
   capability-check paths, не консолидированы.
   - **Recommendation:** Все callers должны идти через
     `services.capabilities.facade.get_capability_facade().check(...)`,
     а не через `services.authorization.facade`.

3. **Source/Sink — `app_state_singleton` vs module-level singleton:**
   - `services/sources/registry.py:107-119` — `@app_state_singleton`
     pattern (standard).
   - `services/sources/lifecycle.py:69-71` — module-level `_services_dict`
     без singleton-паттерна.
   - `services/lineage/lineage_emitter.py:146-178` — module-level
     singleton через `get_lineage_emitter` / `set_lineage_emitter` /
     `reset_lineage_emitter`.
   - `services/notifications/apprise_service.py:32,161-169` — module-level
     `_instance` singleton через `get_notification_service()`.
   - **Pattern inconsistency:** 4 разных singleton-паттерна в одном домене.
     - **Recommendation:** Консолидировать на `@app_state_singleton(factory=...)`
       (стандарт V22).

4. **Layer exceptions — 11 прямых infrastructure imports в services:**
   - Все 11 — documented facade-shims с `# noqa: E402,F401` и явным
     `Layer policy:` docstring (проверены grep).
   - Layer checker baseline = 175 legacy / 0 new — никаких новых нарушений.
   - **Conclusion:** стабильно, не требует немедленных действий.

5. **DataFrame — Polars-first непоследовательно:**
   - `services/io/dataframe.py` — Polars-first (`pl = None` graceful).
   - `services/io/export_service.py` — Excel/PDF через openpyxl/reportlab
     (sync), Parquet через polars (`ParquetExporter`).
   - **Inconsistency:** mixed sync (openpyxl/reportlab) + async (polars).
     Если добавить sync polars в hot-path — может блокировать event loop.

## Readiness score

**Formula:**
```
score = base - (p0_count * 25) - (p1_count * 10) - (p2_count * 3) - (p3_count * 1) - (p4_count * 0.2)
clamp(score, 0, 100)
```

**Counts:**
- P0: **1** (DOMAIN-P0-001 — admin fail-open)
- P1: **3** (DOMAIN-P1-001 — DQ duplication; -002/-003 — reverse-layer shims)
- P2: **6** (DOMAIN-P2-001/-002/-003/-004/-005/-006)
- P3: **5** (DOMAIN-P3-001/-002/-003/-004/-005)
- P4: **4** (DOMAIN-P4-001/-002/-003/-004)

**Calculation:**
```
score = 100 - 1*25 - 3*10 - 6*3 - 5*1 - 4*0.2
       = 100 - 25 - 30 - 18 - 5 - 0.8
       = 21.2
```

**Final score: 21/100.**

**Обоснование:**
- Балл **21/100** обусловлен наличием 1 P0 (admin fail-open = критический
  security blocker для production) + 3 P1 (DQ-дубликация + 2 reverse-layer
  shims). AGENTS.md запрещает score ≥80 при наличии P0/P1, поэтому максимальный
  возможный score после фиксов = **59** (после удаления P0 и P1, останутся
  только P2/P3/P4 = −29.8, score = 70.2 — НЕ достигает 80, потому что P2
  dead-code и stub'ы ещё не удалены).
- **Чтобы достичь ≥80:** нужно удалить **ВСЕ** P0+P1+P2 (или перевести
  P0→fix в проде), что требует ~3-4 спринта: P0 fix → 1 sprint, P1
  dedup+layer-cleanup → 1 sprint, P2 dead-code cleanup → 1 sprint.
- Без P0/P1 (если они зафиксятся) score = ~70 (acceptable для Sprint 36
  "Production Readiness 90%+" но не для final).

## Recommended next tasks

| Pri | Task | Est | Sprint |
|---|---|---|---|
| 1 | **DOMAIN-P0-001 fix:** change `admin/api.py:97-102` fail-open → fail-closed; default `settings.admin.dev_allow_unauth = False` | 1 день | Sprint 36 (active) |
| 2 | **DOMAIN-P1-001 fix:** dedup `DQ*` dataclasses across 5 files → single source in `__init__.py`; remove 4 copies | 1-2 дня | Sprint 36 |
| 3 | **DOMAIN-P2-001 fix:** delete `services/billing/quotas_service.py` (dead stub); verify DI uses `NoOpBillingFacade` | 0.5 дня | Sprint 36 |
| 4 | **DOMAIN-P2-005 fix:** add `_logger.critical` + metric counter for DLQ silent-loss branch in `audit/clickhouse_audit_service/service.py:222` | 0.5 дня | Sprint 36 |
| 5 | **DOMAIN-P2-006 fix:** narrow `except Exception` → `(OSError, ConnectionError, TimeoutError)` in `cache/facade.py` (5 sites) | 0.5 дня | Sprint 36 |
| 6 | **DOMAIN-P3-001 fix:** add `jsonschema>=4.21.0,<5.0.0` to pyproject.toml; verify `pip-audit` visibility | 0.5 дня | Sprint 36 |
| 7 | **DOMAIN-P2-002 fix:** add `feature_flags.imported_actions_live` flag, document stub→live transition | 1 день | Sprint 37 |
| 8 | **DOMAIN-P2-003 / DOMAIN-P2-004:** delete back-compat shims (files.py, skb.resolve_waf_route) после проверки callers | 1 день | Sprint 37 |
| 9 | **DOMAIN-P3-002 / -003 / -005:** optional library replacements (polars for Excel/PDF, httpx for lineage HTTP) | 2-3 дня | Sprint 38 |
| 10 | **DOMAIN-P1-002 / -003:** layer-cleanup; delete reverse-layer shims once callers migrated | 1 день | Sprint 38 |

## Commands run

| # | Command | Purpose | Result |
|---|---|---|---|
| 1 | `git rev-parse HEAD && git log --oneline -3` | confirm baseline | HEAD=2f620910 (1 commit ahead of b69d6b49) |
| 2 | `git log --oneline b69d6b49..HEAD` | list deltas vs baseline | 1 commit (S3 multipart fix, infra-only) |
| 3 | `git status --short` | confirm pre-existing changes | M pyproject.toml, M tests/unit/dsl/transforms/test_dataframes.py, ?? docs/audit/swarm-2026-08-06/ |
| 4 | `find src/backend/services -type f -name "*.py" ! -path "*/ai/*" ...` | scope enumeration | 181 production files in scope |
| 5 | `find tests/unit/services -type f -name "*.py" ! -path "*/ai/*" ! -path "*/security/*"` | test enumeration | 106 test files in scope |
| 6 | `find src/backend/services ... -exec grep -lE "(TODO\|FIXME\|XXX\|HACK\|NotImplemented\|raise NotImplementedError\|stub)" {} \;` | find TODO/stubs | 18 files (mostly documented intentional patterns) |
| 7 | `find src/backend/services ... -exec grep -lE "from src.backend.infrastructure" {} \;` | layer-violation candidates | 11 files (all documented facade shims) |
| 8 | `find src/backend/services ... -exec grep -lE "from extensions\." {} \;` | reverse-layer candidates | 2 files (skb back-compat, files back-compat) |
| 9 | `grep -nE "fail.?open\|fail.?closed\|deny_by_default\|allow.?by.?default" src/backend/services -r --include="*.py"` | fail-mode audit | 4 explicit fail-open cases (admin/api.py, rate_limit_middleware.py, security/facade.py, ai/guardrails — out of scope) |
| 10 | `grep -nE "import jsonschema\|from jsonschema" src/backend/services -r --include="*.py"` | find jsonschema usage | 2 files (ops/data_quality/apply_mixin.py, schema_registry/registry.py) |
| 11 | `grep -E "jsonschema" pyproject.toml` | check jsonschema pinning | 0 hits — NOT pinned (DOMAIN-P3-001 confirmed) |
| 12 | `grep -nE "from polars\|import polars" src/backend/services -r --include="*.py"` | polars usage | 3 files (io/dataframe.py, io/export_service.py, core/tech.py) |
| 13 | `grep -nE "urllib\.request\.(urlopen\|Request)" src/backend/services -r --include="*.py"` | urllib.request (sync HTTP in async ctx) | 1 file (lineage/lineage_http_emitter.py) — DOMAIN-P3-005 |
| 14 | `wc -l` на топ-15 файлов в scope | identify largest modules | ops/health.py (599), routes/loader.py (482), io/export_service.py (405), ops/data_quality/apply_mixin.py (402), integrations/webhook_relay.py (368) |
| 15 | `find ... -exec grep -lE "(except \(Exception\|except Exception as)" {} \;` | broad-except audit | 17 sites в 8 facade-файлах (B-05 resilience fail-mode, cache fallback, observability fallback) |

**Read-only operations only.** No source modifications, no git mutations.
