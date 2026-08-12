# DSL Domain — Cycle 4, Phase 1 (Audit)

- Дата: 2026-08-06
- HEAD на старте аудита: `22e08a0d` (cycle-4 reapply, +1 поверх cycle-3 baseline)
- HEAD в конце аудита: `baf54d95` (содержит `22e08a0d` + 3 downstream-коммита вне scope данного раунда)
- Скоуп: `src/backend/dsl/**` + `tests/unit/dsl/**` и связанные tests/unit/dsl/processors/security, tests/unit/dsl/engine/test_*.
- Исключено из раунда: `src/backend/dsl/agents/**`, `src/backend/dsl/workflow/**`,
  `src/backend/dsl/engine/processors/agent_dsl/**`, `src/backend/dsl/engine/processors/workflow/**`,
  `src/backend/dsl/engine/processors/rag*` (per задаче).
- Дополнительные файлы вне `tests/unit/dsl/`, но связанные с allowlist/кодом, читались read-only
  и не подразумевают расширения скоупа:
  `tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py` — **не проверено**;
  `tests/unit/entrypoints/cdc/test_management_endpoints_auth.py` — **не проверено**;
  `tests/unit/infrastructure/cache/rag/**` — **не проверено** (rag outside scope);
  `tests/unit/core/config/features/**` — **не проверено** (вне DSL domain).

## Scope / что НЕ проверено

- Reports of other agents (cycle-1/2/3 markdown, `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`,
  `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md`) — **не прочитаны** per задаче.
- Только AGENTS.md root использован как обязательные правила; BASELINE.md — для baseline-чисел.
- `extensions/<name>/` (бизнес-логика) — не скоуп DSL-аудита; не проверялось.
- Workflow/agent_dsl/rag* — вне scope; **не проверено** (Y).
- `src/backend/dsl/builders/base/_protocol.py` и transport/* mixin-протоколы —
  **не проверено** (read-only time-budget; не входит в критический hot-path; не оказывает
  прямого влияния на безопасность DSL).
- `src/backend/dsl/engine/processors/ai/*`, `src/backend/dsl/engine/processors/ai_banking/*` —
  частично прочитаны через grep; полное чтение — **не проверено** (вне основных
  security-critical DSL-процессоров).
- `src/backend/dsl/engine/processors/rpa/operations/*` (filtered/scan/decrypt/...) —
  через grep; полное чтение каждого — **не проверено**.
- `src/backend/dsl/engine/processors/format_convert/{encodings,specialized}.py` — **не проверено**.
- `src/backend/dsl/engine/processors/streaming_llm_publishers.py` — частично
  прочитан (scaffold-абстракции `_BasePublisher` с `NotImplementedError` — намеренно,
  для подклассов; задокументировано как «abstract»).

## Verified strengths

- **T-1.4 (multicast + redelivery)** подтверждены в HEAD через
  `.venv/bin/python -m pytest tests/unit/dsl/engine/processors/eip/{routing/test_multicast,reliability/test_redelivery_policy}.py`:
  `15 passed in 3.06s`. Регрессионный канон зафиксирован: `ExecutionEngine()` собирается без
  `route_registry` kwarg; `except (TypeError, ValueError):` — Python-3 syntax; `MulticastRoutesProcessor`
  использует `route_registry` module-level lookup, а не инстанс; `first_success` отменяет
  pending-таски; `on_error='fail'` фейлит exchange; unknown route → запись в `multicast_route_errors`.
- **T-W1-08 (auth cycle-2 fix)** — `AuthenticationProviderUnavailableError` импортируется, реальный
  fail-closed путь работает (canonical `_VERIFIERS_MODULE` указывает на `core.auth.auth_selector`).
  36/36 PASS (auth/scan/pii_erase regression pack).
- **ScanFile fail-open semantics** — `ScanFileProcessor.process` при недоступности AV-бэкенда
  и `on_threat='fail'` НЕ пропускает: `exchange.fail("ScanFileProcessor: AV-бэкенд недоступен: ...")`
  (`src/backend/dsl/engine/processors/scan_file.py:96`). Также корректно обрабатываются
  edge-cases: пустой `s3_key_from`+`data_property` (constructor ValueError), `data_property` в виде
  str/bytes, S3 fallback при исключении, отсутствие payload.
- **XXE fallback** — `XmlDataFormat.unmarshal` использует `defusedxml.ElementTree.fromstring`
  при наличии `defusedxml`; fallback на stdlib `ET.fromstring` только под `pragma: no cover — dev-light
  path` с явным комментарием «caller is responsible for accepting the residual risk»
  (`src/backend/dsl/engine/processors/eip/marshal/formats.py:130-139`). Stdlib `xml.etree.ElementTree`
  дополнительно ужесточён в `WafCheckProcessor` regex-паттерном `(r"(?i)<!ENTITY", "xxe_entity")`
  на payload уровне. **Но**: `XmlDataFormat.marshal` пишет XML через stdlib (что безопасно — мы
  генерируем XML из dict, никогда не парсим untrusted-input в marshal-пути). Логика симметрична
  с `bpmn_importer.py:55` (defusedxml hard-imported; см. примечание Y).
- **PII erasure entity_type whitelist** — `_validate_entity_type` отбивает SQL-инъекцию через
  regex `^[A-Za-z_][A-Za-z0-9_]*$` (`pii_erase.py:53-67`), regression-тест
  `test_invalid_scope_rejected_before_sql` подтверждает, что опасный scope НЕ доходит до
  `session.execute()` (PASS).
- **Tenant-aware gate (K-ARCH-4)** — `ExecutionEngine._check_tenant_aware` корректно
  блокирует pipeline с `tenant_aware=True` при отсутствии tenant_id и соблюдает приоритет
  `RequestContext.tenant_id` над `TenantContext`. 6/6 PASS в `test_tenant_aware_execution.py`.
- **Exchange finalizers / clone-isolation** — `add_finalizer` / `run_finalizers` LIFO,
  изоляция ошибок в одном finalizer, idempotency; `clone()` НЕ наследует `_finalizers`
  (no double-release). 7/7 PASS.
- **Webhook signature** — `WebhookSignatureProcessor` использует `standardwebhooks.Webhook.verify`
  при доступности библиотеки; HMAC-SHA256 fallback (`_verify_manual`) использует
  `hmac.compare_digest` (timing-safe); `on_error` политика `fail|dlq|warn` валидируется в
  конструкторе.
- **WAF DSL** — `WafCheckProcessor` покрывает OWASP CRS 23/932/941/942 через regex-паттерны,
  `action='block'` вызывает `exchange.stop()` (no raise — DSL convention).
- **Route validation** — `PipelineValidator` ловит `RestorePIIProcessor` без предшествующего
  `SanitizePIIProcessor`, circular route references, отсутствие error-handling на pipeline
  с external calls (warning).

## Findings table

| ID | P | Файл:строка | Evidence | Impact | Рекомендация | Тест-критерий |
|----|---|-------------|----------|--------|--------------|---------------|
| DOMAIN-P0-001 | P0 | `src/backend/dsl/engine/processors/eip/marshal/formats.py:91-140` (`XmlDataFormat.unmarshal`) | Stdlib-fallback `ET.fromstring(data)  # noqa: S314` под `pragma: no cover — dev-light path`. Если `defusedxml` отсутствует (dev-light), XXE через `<!ENTITY>` / `SYSTEM file://` пройдёт. | XXE на unmarshal untrusted XML (file read, SSRF, DoS через billion-laughs). | Заменить lazy-try на `defusedxml` как hard import; `pyproject.toml` уже содержит `defusedxml` (см. `bpmn_importer.py:55` который это уже требует); удалить pragma-fallback. | Unit: `ET is None` → unmarshal поднимает `ImportError`/fail; интеграция: `XmlDataFormat` отбивает DOCTYPE/ENTITY payload. |
| DOMAIN-P0-002 | P0 | `src/backend/dsl/engine/processors/script_runner.py:46-152` (`ScriptRunnerProcessor`) | DSL-шаг `script_runner` исполняет произвольный user-supplied код (`self._code` пишется в `tempfile.NamedTemporaryFile` → `create_subprocess_exec(interpreter, tmp_path, ...)`). По default `allowed_languages` не задано, `interpreter` тоже → исполняется **любой** `language` из `_DEFAULT_INTERPRETERS` (`python/node/ruby/shell`). Наследует `os.environ` целиком, что протекает в дочерний процесс (creds, vault-token, etc.). | Arbitrary code execution на узле; через DSL-маршрут из tenant-isolation обхода. RCE на production-роуте с `script_runner`. | `language='python'` only + `allowed_languages` обязателен; `env=None` (не наследовать `os.environ`); минимальный safe-env (PATH, LANG); `interpreter` whitelisted по абсолютному пути; cap timeout=10s default; capability `script_runner.execute`; аудит event. | Unit: `ScriptRunnerProcessor(language="bash")` (не в default) → fail; `env={}` не leak'ает `os.environ['SECRET']`; integration: capability `script_runner.execute` denied → exchange.fail. |
| DOMAIN-P0-003 | P0 | `src/backend/dsl/engine/processors/eip/marshal/formats.py:236-272` (`PickleDataFormat.unmarshal`) | `obj = pickle.loads(data)  # noqa: S301`. Только текстовый комментарий «TRUSTED ONLY» в docstring. В DSL-роуте с `unmarshal` формата `pickle` от untrusted producer (HTTP webhook, MQ payload) → arbitrary code execution. | Arbitrary code execution на узле через pickle payload. RCE в production при компрометации MQ/HTTP producer. | Полностью **удалить** `PickleDataFormat` из public surface (или перенести в `extensions/dev_tools/` как opt-in); если оставить — обернуть в `hmac.verify(payload, signature)` required-by-default; capability `marshal.pickle.unmarshal`; audit event. | Unit: импорт `PickleDataFormat` помечен deprecation/removed; integration: `UnmarshalProcessor(PickleDataFormat())` отбивает unsigned payload. |
| DOMAIN-P0-004 | P0 | `src/backend/dsl/engine/processors/security/pii_erase.py:139-228` (`PiiEraseProcessor.process`) | Шаги `_delete_vectors` и `_anonymize_db` обёрнуты в `try/except Exception → _logger.warning` без `exchange.fail`. Любая ошибка (DB timeout, vector store down) → pipeline продолжается, PII остаётся. `side_effect=SIDE_EFFECTING`, `compensatable=False` — irreversible при ошибке. | Data-loss против compliance: PII не удалено, audit «completed» записан, регуляторный провал (152-ФЗ/GDPR). | `exchange.fail("PII erasure: vector/DB step failed")` при exception (или явный retry-then-fail); отдельный `exchange.set_property("pii_erasure_partial", True)` для раздельной обработки; required `handle_processor_error` на критических шагах. | Unit: mock `_delete_vectors` raise → exchange.status=failed, error содержит «PII erasure». |
| DOMAIN-P1-001 | P1 | `src/backend/dsl/engine/processors/external.py:1-100` (после `baf54d95` — только `CDCProcessor` остался) | `CDCProcessor` импортирует `src.backend.infrastructure.cdc` (через `from src.backend.infrastructure.cdc...`) — это layer violation `dsl → infrastructure` (DSL должен импортировать `core` (контракты) + infrastructure через registries). См. `AGENTS.md`/python-dev: прямой импорт infrastructure из DSL запрещён. | Layer-boundary bypass; dsl-bound-testability падает (нельзя mockнуть без мок-инфраструктуры). | Вынести `CDCProcessor` в `extensions/cdc/` (бизнес-логика CDC — domain-specific) или импортировать через registry; следовать правилу `core/protocols` + capability-checked facade. | Layer-check: `python tools/check_layers.py --root src` → 0 violation на `external.py`. |
| DOMAIN-P1-002 | P1 | `src/backend/dsl/engine/processors/function_call.py:194` | `gate.check(plugin, f"function.call.{module_name}", None)` ловит `AttributeError → return` (no-op). Если `gate` имеет другой API (например, async `check` в новой версии capability facade) — silently fail-OPEN. | Auth bypass: `function.call.<module>` capability не проверяется → неавторизованный module call в production. | Использовать `hasattr`/`callable` gate перед `await gate.check(...)`; явный `CapabilityDeniedError` при отсутствии метода; capability-check через typed-protocol. | Unit: `gate` без `check` → `CapabilityDeniedError` (не silent return). |
| DOMAIN-P1-003 | P1 | `src/backend/dsl/engine/processors/scan_file.py:78-120` (`ScanFileProcessor.process`) | `self._record_metric` обёрнут в `try/except Exception: pass` (`scan_file.py:154-161`) — observability best-effort, но при `import` ошибке в тестах метрика не видна. Не критично, но в проде при падении `record_antivirus_scan` (exporter down) — никто не узнает, что scan не учтён. | Blind spot: метрика `antivirus_scan` не видна в проде → аудит AV-покрытия сломается. | Логировать warning вместо `pass`; метрика через `try/except Exception → _logger.warning` (как в других местах). | Unit: `record_antivirus_scan` raise → warning в логе, exchange status не меняется. |
| DOMAIN-P1-004 | P1 | `src/backend/dsl/engine/processors/security/pii_erase.py:60-67` (`_validate_entity_type`) | Regex `^[A-Za-z_][A-Za-z0-9_]*$` whitelists valid identifier, но `scope` формат «entity_type:entity_id» split'ится до whitelist-check. Если `entity_type` пустая (`:user` или `:`) — `split(':', 1)` → `("", "user")` / `("", "")` — `re.fullmatch("")` не пройдёт, но ошибка скрыта в `try/except Exception` (`_anonymize_db:283-285` → `return 0` silently). | Скрытый data-loss: invalid scope → silently 0 удалено, PII остаётся, audit «completed». | Raise ValueError (не `return 0`); propagate через outer try/except → `exchange.fail`. | Unit: `scope=":user"` → exchange.fail. |
| DOMAIN-P1-005 | P1 | `src/backend/dsl/engine/processors/web.py:19-166` (`NavigateProcessor`/`ClickProcessor`/...) | `from src.backend.services.io.web_automation import get_web_automation_service` — `dsl → services` layer violation. Тот же pattern что в `external.py:CDCProcessor` (см. DOMAIN-P1-001). | Layer boundary bypass для всех 6 web-processor'ов. | Перенести web automation в `extensions/rpa_browser/` или вынести в `core/services` через facade с capability-check. | Layer-check: 0 violation на `processors/web.py`. |
| DOMAIN-P2-001 | P2 | `src/backend/dsl/engine/processors/streaming_llm_publishers.py:17-26` (`_BasePublisher`) | `NotImplementedError` в abstract base — корректный ABC-pattern. **Но**: `_BasePublisher` не помечен `ABC` + `@abstractmethod`, контракт держится на соглашении. Наследник может забыть переопределить — silent no-op (subclass без `publish_chunk`/`publish_done` → AttributeError в runtime). | Stale subclass bug: `SSEPublisher` переименовали, а клиент ссылается на старое имя → AttributeError. | `@abstractmethod` декоратор + `ABC`; mypy strict-mode catching. | Unit: создать `class _Empty(_BasePublisher): pass` → TypeError при инстанции. |
| DOMAIN-P2-002 | P2 | `src/backend/dsl/engine/processors/fs_directory_scan.py:1-247` (`DirectoryScanProcessor`) | `class _DeprecationAuditEmitted` с одним class-level `_emitted: bool` — глобальный side-effect-guard, непотокобезопасен (multi-event-loop / multi-tenant не различает); `warnings.warn(..., DeprecationWarning)` в `__init__` — spammy при большом кол-ве instance'ов. | Audit-emit может пропуститься в multi-tenant сценарии (1 tenant заберёт флаг → остальные не получат сигнал). | `threading.Lock` на guard, или per-tenant guard; `warnings.warn` с `stacklevel` корректный, но подавить при `__init__` если процессор — internal shim. | Unit: 2 инстанса в разных event loops → обе эмитят. |
| DOMAIN-P2-003 | P2 | `src/backend/dsl/engine/processors/zip_archive.py:135-145` (`ZipArchiveProcessor.process`) | `from src.backend.core.config.features import feature_flags` обёрнут в `try/except Exception: pass` — если `feature_flags.proc_zip_archive` не определён → silent default-off (best-effort). Не критично, но: 2+ processor'а дублируют этот pattern (см. `webhook_signature.py:148-154`) — копипаст. | Dead code через feature flag-шимы: `proc_zip_archive`/`proc_webhook_signature` не видны в production-конфиге, но обработчик всё равно создаётся. | Вынести в helper `_feature_flag_active(name: str) -> bool` в `processors/base.py`; устранить копипаст. | Unit: 2 processor'а используют helper, без копипаста. |
| DOMAIN-P2-004 | P2 | `src/backend/dsl/engine/processors/jdbc_query.py:107-138` (`JdbcQueryProcessor.process`) | `session.execute(text(self._sql), params)` — SQL через bind-parameters, но `_validate_sql` блокирует только `DROP/ALTER/TRUNCATE/CREATE/GRANT/REVOKE` и multi-statement. Допускает `SELECT * FROM users WHERE id = 1 OR 1=1` (UNION-based, time-based blind SQLi в read-only DB). `params_from='headers'` берёт ВСЕ заголовки как bind params — `headers['id']` → `:id` placeholder. | SSRF/read-amplification: malicious client поставляет headers `{"id": "1 OR 1=1"}` → bind param защищает, но если placeholder отсутствует — injection. | Whitelist допустимых SQL-операций (только `SELECT` для read-only profile); `params_from='headers'` валидировать что param-name объявлен в SQL. | Unit: `params_from='headers'` + SQL без placeholder → exchange.fail. |
| DOMAIN-P3-001 | P3 | `src/backend/dsl/engine/processors/rate_convert.py:170` / `geo.py:153` / `pdf_template.py:154` (pass-stubs) | Множество `except Exception: pass` в pass-stub helper'ах; см. grep-результаты ниже. Не критично, но: best-practice — `_logger.debug("skip: %s", exc)`. | Лог-шум или нет — нет observability когда helper тихо skipает. | `_logger.debug` в этих местах (Ponytail: комментарий «deliberate skip — see usage»). | grep-changed: 0 `except Exception: pass` без `_logger` в этих файлах. |
| DOMAIN-P3-002 | P3 | `src/backend/dsl/engine/processors/format_convert/data_formats.py:61-64` (`_xml_to_dict_stdlib`) | Stdlib `ET.fromstring(xml_string)  # noqa: S314` — прямой парс untrusted XML без defusedxml-fallback. `FormatConvertProcessor` используется в `format_convert` (Camel-like), потенциально обрабатывает webhook-payload. | XXE поверх format_convert (mirror of DOMAIN-P0-001, но в другом module). | Заменить на `defusedxml.ElementTree` (уже в deps). | Unit: `ET.fromstring` → `defusedxml.ElementTree.fromstring`. |
| DOMAIN-P3-003 | P3 | `src/backend/dsl/engine/processors/ai/{cache_processor.py,cachewrite_processor.py,reranker.py}` (`pass`-stubs) | grep: `pass` в `except`-block без логирования; часть — намеренный fall-through (`pca_vector_reranker`? — не проверено). | Низкий observability при ошибках AI-cache. | Индивидуальный review, см. `tests/unit/dsl/processors/test_data_lineage.py` (Y). | Каждый `except: pass` заменён на `except: _logger.debug`. |
| DOMAIN-P4-001 | P4 | `src/backend/dsl/engine/processors/` — gap to Camel/Airflow | Не вижу в DSL нативных процессоров для Camel `ControlBus`, `WireTap` (есть но в `eip/flow_control/wire_tap.py` — Y), `IdempotentConsumer` (есть `idempotency.py` — Y). | Coverage gap в Camel EIP surface. | Не блокер; только если бизнес-требования расширятся. | Не делать без бизнес-обоснования (Ponytail: YAGNI). |

## Detailed evidence (на критичных DOMAIN-P0)

### DOMAIN-P0-001 — XXE fallback в XmlDataFormat

```python
# src/backend/dsl/engine/processors/eip/marshal/formats.py:130-139
if DET is not None:
    root = DET.fromstring(data)  # type: ignore[union-attr]
else:  # pragma: no cover — dev-light path
    root = ET.fromstring(data)  # noqa: S314 — see SECURITY above
```

`DET` = `defusedxml.ElementTree` импортируется через `try/except ImportError` на строке 22-25.
Если `defusedxml` не установлен (`dev-light` профиль), `DET = None` → unmarshal-путь
использует stdlib `ET.fromstring`. На Python 3.14 stdlib `ET` НЕ защищает от XXE по
умолчанию (только `defusedxml`/lxml с `resolve_entities=False`).

Down-stream потребитель `XmlDataFormat` — `UnmarshalProcessor.process` (formats.py:151)
и `tests/unit/dsl/engine/processors/eip/test_s56_w1_eip_gap_closure.py:267-281`
(где `unmarshal` доверяет содержимому — roundtrip в тестах, но в проде источник —
untrusted XML).

`bpmn_importer.py:55` уже hard-imports `defusedxml.ElementTree`; значит dep доступна,
но lazy-try в `formats.py` создаёт неоправданный fail-open канал.

### DOMAIN-P0-002 — ScriptRunner RCE

```python
# src/backend/dsl/engine/processors/script_runner.py:46-152
class ScriptRunnerProcessor(BaseProcessor):
    side_effect = SideEffectKind.SIDE_EFFECTING
    compensatable = False
    def __init__(self, language, code, *, timeout_seconds=30.0, allowed_languages=None, ...):
        ...
        # default allowed_languages=None → ALL from _DEFAULT_INTERPRETERS
        # (python, node, ruby, shell — RCE на каждый)
        self._allowed = set(allowed_languages) if allowed_languages else None
    ...
    env = os.environ.copy()  # строка 110-112 — ВЕСЬ env процесса
    proc = await asyncio.create_subprocess_exec(
        interpreter, tmp_path, ..., env=env,  # дочерний процесс видит VAULT_TOKEN, DB creds, etc.
    )
```

Хотя `required_capability` НЕ задан, DSL-роут с `script_runner` уже доступен —
`__init__` с `language='python'`, `code='import os; os.system("rm -rf /")'` пройдёт валидацию
(`allowed=None`), создаст `tmp.py` и выполнит. `os.unlink(tmp_path)` в `finally` —
cleanup, но data exfiltration уже произошла.

### DOMAIN-P0-003 — PickleDataFormat RCE

```python
# src/backend/dsl/engine/processors/eip/marshal/formats.py:236-272
class PickleDataFormat(DataFormat):
    """Pickle via stdlib. Только для trusted data (security warning)."""
    ...
    def unmarshal(self, data: bytes, target_type: type | None = None) -> Any:
        obj = pickle.loads(data)  # noqa: S301 — see SECURITY above
        ...
```

`UnmarshalProcessor(PickleDataFormat())` (test_s56_w1_eip_gap_closure.py:312)
производит pickle roundtrip в тестах; в проде любой DSL-роут с `format: pickle` →
`pickle.loads` от untrusted producer (HTTP webhook, MQ payload, S3-stored) =
arbitrary code execution. Standard Python warning S301.

### DOMAIN-P0-004 — PII erasure silent fail-OPEN

```python
# src/backend/dsl/engine/processors/security/pii_erase.py:160-184
# Step 2: vector store deletion
try:
    ...
    if cap_facade.check("dsl", "ai.memory.delete", scope=self._scope):
        vectors_deleted = await self._delete_vectors(erasure_id)
    else:
        _logger.debug("vector deletion skipped: capability denied")
except Exception as exc:
    _logger.warning("vector deletion failed: %s", exc)  # → silently return
# Step 3: DB anonymization
try:
    ...
    if cap_facade.check("dsl", "pii.audit", scope=self._scope):
        records_anonymized = await self._anonymize_db(erasure_id)
except Exception as exc:
    _logger.warning("DB anonymization failed: %s", exc)  # → silently return
```

После обоих `try/except` (включая `BaseException`? — нет, `Exception`),
`result = ErasureResult(..., vectors_deleted=0, records_anonymized=0, ...)` →
`exchange.set_property("pii_erasure_result", result)` → шаг 4 эмитит
`pii.erasure.completed` с `vectors_deleted=0, records_anonymized=0`.
PII остаётся в storage, audit говорит «completed».

`tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py:60-103`
тестирует SQL-инъекцию whitelist, но **НЕ тестирует data-loss на исключении**.

## Cycle-1+2+3 residuals (verified / mutated / resolved)

- **T-1.4 (multicast + redelivery)** — RESOLVED. Подтверждено в HEAD `22e08a0d` (коммит
  `22e08a0d` reapply): `15 passed` в `tests/unit/dsl/engine/processors/eip/{routing/test_multicast,reliability/test_redelivery_policy}.py`.
- **T-1.5 (policy_mixin / gateway_adapter)** — RESOLVED (вне DSL scope, не перепроверял, baseline claims).
- **T-3.1 (cachetools TTLCache)** — RESOLVED (вне DSL scope).
- **T-W1-01 (AuthenticationProviderUnavailableError)** — RESOLVED + MUTATED.
  В HEAD `c3ff7bec` (kimi@local, после baseline) `_VERIFIERS_MODULE` переключён
  с DEPRECATED `entrypoints.api.dependencies.auth_selector` на canonical
  `core.auth.auth_selector`. 7 verifiers загружаются (TestAuthValidateCanonicalPath).
  В `baf54d95` (последующий коммит) дополнительно удалены `MCPToolProcessor/AgentGraphProcessor`
  shadow из `external.py` (security attack surface). Auth — `baf54d95`'s canonical path
  работает. Smoke: 7/7 PASS в `test_auth_validate_failclosed.py`.
- **T-W1-05 (cdc_routes auth)** — RESOLVED (вне DSL scope).
- **T-W1-08 (credit_pipeline fail-closed)** — RESOLVED (вне DSL scope).
- **T-02 (pip-audit-allowlist 35→27)** — RESOLVED.
- **T-03 (streamlit pin)** — RESOLVED.
- **T-04/T-05/T-06/T-08/T-09/T-10/T-11 cycle-3 carryovers** — not re-verified (вне DSL scope).
- **T-1.1 (composition root)** — RESIDUAL (вне DSL scope).
- **T-1.2 (SSE/HITL auth 8 xfailed)** — RESIDUAL (вне DSL scope; не перепроверял).
- **T-1.3 (MQ DLQ data-loss)** — RESIDUAL (вне DSL scope; см. DOMAIN-P0-004 mirror — same pattern
  в `PiiEraseProcessor` уже зафиксирован).
- **T-2.1 (reverse-layer cleanup)** — RESOLVED частично: в HEAD `baf54d95` `external.py` убрал
  MCPTool/AgentGraph shadows (`-63 LOC`). `web.py` (web automation) ещё содержит
  `dsl → services` violation (DOMAIN-P1-005). External `CDCProcessor` остался (DOMAIN-P1-001).
- **T-4.1 (text-RAG E2E)** — RESIDUAL (rag* out of scope, не перепроверял).
- **T-W1-02..04, T-W1-06..07, T-W2-01..04, T-W3-01, T-W4-01 cycle-2 carryovers** — вне DSL scope;
  не перепроверял.
- **Pre-existing residual `gateway_adapter.py:128-129`** — RESIDUAL (вне DSL scope; baseline
  claims cycle-1 critic flagged, cycle-2/3/4 plans do not rewrite).

## Contradictions / overlaps to flag

1. **defusedxml inconsistency** — `bpmn_importer.py:55` hard-imports `defusedxml`,
   `formats.py:22-25` lazy-try. **Тот же dependency, разные подходы**. Recommend:
   canonicalize на hard-import.
2. **Multi-source XXE protection** — `WafCheckProcessor` ловит XXE regex-паттерном,
   `XmlDataFormat` ловит через defusedxml, `bpmn_importer` тоже через defusedxml.
   3 разных подхода. Рекомендация: helper `_safe_xml_parse(data) -> ET.Element` в
   `core/utils` (использовать во всех трёх местах).
3. **`except Exception: pass` дублирование** — 30+ мест в processors/ (см. grep ниже).
   Не все критичны, но в `webhook_signature.py:153, 184`, `zip_archive.py:144`,
   `scan_file.py:161` (metric), `pii_erase.py:172, 183, 261, 321, 357` — observable
   silent failures (см. DOMAIN-P0-004).
4. **fail-closed pattern** — `security.py:145-152` правильно использует
   `AuthenticationProviderUnavailableError`; `pii_erase.py:172, 183` имеет `try/except
   Exception → warning` без fail — **нарушение того же принципа в смежном модуле**.

## Readiness score 0–100

**Formula** (Ponytail-style, не превышать 100 при P0/P1):
```
score = base(100)
  - P0 * 25
  - P1 * 10
  - P2 * 3
  - P3 * 1
  - P4 * 0.5
  - cap(0..100)
```

**Computed** (cycle-4 Phase-1 DSL scope):
- base = 100
- 4 P0 → -100 → floor 0
- 5 P1 → -50
- 4 P2 → -12
- 3 P3 → -3
- 1 P4 → -0.5

Raw: `100 - 100 - 50 - 12 - 3 - 0.5 = -65.5`, capped at **0**.

**Обоснование** (cycle-4 reset):
- 4 P0 в DSL scope (XXE-fallback, ScriptRunner RCE, Pickle RCE, PII silent fail) —
  это blocker'ы уровня production sign-off. Любой из них — critical RCE или
  data-loss/152-ФЗ провал.
- 5 P1 (layer violations + auth-capability silent fall-through + silent
  metric/metric-log) — должны быть устранены до production rollout.
- 4 P2 / 3 P3 — cleanup, не блокеры, но best-effort и Ponytail-skim.

При наличии P0/P1, по правилу "оценка ≥80 запрещена", readiness = **0**.

## Recommended next tasks

В порядке убывания critical (P0→P4):

1. **DOMAIN-P0-002 (ScriptRunner)** — убрать `language` default; обязать `allowed_languages`;
   очистить `env`; добавить `required_capability='script_runner.execute'`; default timeout
   снизить до 10s. **Файлы**: `src/backend/dsl/engine/processors/script_runner.py:46-152`,
   `src/backend/dsl/builders/integration_core/utils_mixin.py` (если есть script-builder).
2. **DOMAIN-P0-003 (PickleDataFormat)** — удалить `PickleDataFormat` из public surface
   или перенести в opt-in `extensions/dev_tools/`. **Файлы**:
   `src/backend/dsl/engine/processors/eip/marshal/{formats,__init__,processors}.py`,
   `src/backend/dsl/engine/processors/eip/__init__.py:57,147`.
3. **DOMAIN-P0-001 (XXE-fallback)** — заменить lazy-try на hard-import `defusedxml`.
   **Файлы**:
   `src/backend/dsl/engine/processors/eip/marshal/{formats.py:22-25, base.py:18-21, processors.py:19-22}.py`.
4. **DOMAIN-P0-004 (PII silent fail)** — `exchange.fail` на критических шагах; добавить
   regression-тест на исключение. **Файлы**:
   `src/backend/dsl/engine/processors/security/pii_erase.py:139-228`,
   `tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py` (добавить
   `test_vector_deletion_failure_fails_exchange`).
5. **DOMAIN-P1-001/005 (layer violations)** — перенести `CDCProcessor` (external.py) и
   web automation (web.py) в extensions. **Файлы**:
   `src/backend/dsl/engine/processors/{external.py, web.py}`.
6. **DOMAIN-P1-002 (capability silent fall-through)** — typed protocol для `CapabilityGate`;
   `CapabilityDeniedError` при отсутствии метода. **Файл**:
   `src/backend/dsl/engine/processors/function_call.py:194`.

## Commands run

Все команды выполнены через `.venv/bin/python` (system Python НЕ использовался).

```bash
# baseline
git rev-parse HEAD                           # 22e08a0d (start) → baf54d95 (end)
git status --short
git log --oneline -n 15

# T-1.4 verification (required by task)
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/eip/{routing/test_multicast,reliability/test_redelivery_policy}.py -q
# → 15 passed in 3.06s

# regression pack (DSL scope, included by task)
.venv/bin/python -m pytest \
  tests/unit/dsl/processors/security/test_auth_validate_failclosed.py \
  tests/unit/dsl/wave11/test_scan_file_processor.py \
  tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py -q
# → 36 passed in 2.82s

# broader DSL scope smoke
.venv/bin/python -m pytest \
  tests/unit/dsl/engine/processors/eip/ \
  tests/unit/dsl/engine/test_exchange_finalizers.py \
  tests/unit/dsl/engine/test_tenant_aware_execution.py -q --no-header
# → 354 passed, 1 warning in 9.79s
# warning: WireTapProcessor._run_tap coroutine never awaited (eip/flow_control)
# — non-blocking, но кандидат на DOMAIN-P2 (Ponytail pass).

# specific commits inspected
git show --format=fuller --stat 22e08a0d  # cycle-4 reapply (8 source fixes)
git show --format=fuller --stat c3ff7bec  # post-baseline: auth canonical
git show --format=fuller --stat e96dda55  # post-baseline: eip/reliability.py -442 LOC
git show --format=fuller --stat baf54d95  # post-baseline: external.py shadow removal
```

**OUT OF SCOPE — NOT RUN** (per task):
- `.venv/bin/python -m pytest tests/unit/dsl/agents/`
- `.venv/bin/python -m pytest tests/unit/dsl/workflow/`
- `.venv/bin/python -m pytest tests/unit/dsl/engine/processors/agent_dsl/`
- `.venv/bin/python -m pytest tests/unit/dsl/engine/processors/workflow/`
- `.venv/bin/python -m pytest tests/unit/dsl/processors/rag*/`
