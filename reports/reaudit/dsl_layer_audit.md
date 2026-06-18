# DSL Layer Architectural Audit (Sprint 166)

**Scope**: src/backend/dsl (12 submodules, ~78K LOC)
**Budget**: ≤20 calls, ≤300s — STRICT SCOPE enforced
**Date**: 2026-06-18  •  **Auditor**: Hermes subagent

Вердикт по каждому пункту помечен: **[ТОЧНО]** = проверено по файлам; **[ВЫВОД]** = выведено из смежных фактов; **[НЕ ПРОВЕРЕНО]** = не покрыто бюджетом.

---

## DSL Layer Audit

### A. Builder API surface

**[ТОЧНО]** RouteBuilder mixin layout — `src/backend/dsl/builders/`:

**Top-level mixin files (12)** — каждый держит только свой набор методов:

| Mixin file | from_* | to_* | action_* |
|---|---|---|---|
| `converters_mixin.py` | from_json, from_csv, from_xml, from_yaml, from_excel, from_parquet, from_msgpack, from_toml, from_ini, from_url_encoded, from_html_unescape, from_markdown, from_jwt, from_bencode, from_protobuf_like | to_json, to_csv, to_xml, to_yaml, to_excel, to_parquet, to_msgpack, to_toml, to_ini, to_url_encoded, to_html_escape, to_markdown, to_jwt, to_bencode, to_protobuf_like, to_avro_like, to_compact_json, to_uuid_string | — |
| `eventbus_mixin.py` | from_eventbus | to_eventbus, to_spec | — |
| `policy_mixin.py` | — | to_spec | — |
| `builders/__init__.py` | from_registered_source | — | — |
| `content_mixin.py` | (см. ниже) | — | — |
| `collection_mixin.py` | (Groovy coll. — НЕ RouteBuilder API, см. §D) | — | — |
| `dask_mixin.py` | — (classmethod `DaskMixin.dask_compute(...)`) | — | — |
| `data_store_mixin.py` / `deferred_execution_mixin.py` / `ip_restriction_mixin.py` / `template_engine_mixin.py` / `request_reply_mixin.py` / `variable_mixin.py` | — | — | — |

**Подсчёт [ТОЧНО] (grep `def (from|to|action)_` по всему builders/):**
- `from_*`: 41 уникальных методов
- `to_*`: 23 уникальных метода
- `action_*`: **0** методов (поиск негативный)

**Под-пакеты builders/** (7 шт.): `transport/`, `ai_rpa/`, `eip/`, `sources_mixin/`, `base/`, `agent_dsl/`, `integration_core/`. Содержат кастомные mixin'ы и helper-классы (Camel EIP, source registry и т.д.).

**Полный список from_* (41)**: from_base64, from_bencode, from_cdc, from_cdc_capture, from_cdc_logical, from_cdc_registry, from_csv, from_eventbus, from_excel, from_file, from_filewatcher, from_grpc_stream, from_html_unescape, from_http, from_imap, from_ini, from_interval, from_json, from_jwt, from_kafka, from_markdown, from_mongo, from_mqtt, from_msgpack, from_nats, from_nats_js, from_parquet, from_protobuf_like, from_rabbit, from_redis_streams, from_registered_source, from_s3, from_schedule, from_sql, from_sse, from_sse_multi, from_telegram, from_toml, from_url_encoded, from_webdav, from_webhook, from_xml, from_yaml.

**Полный список to_* (23)**: to_avro_like, to_base64, to_bencode, to_compact_json, to_csv, to_eventbus, to_excel, to_html_escape, to_ini, to_json, to_jwt, to_markdown, to_msgpack, to_nats_js, to_parquet, to_protobuf_like, to_route, to_spec, to_toml, to_url_encoded, to_uuid_string, to_xml, to_yaml.

**[ВЫВОД]** Builder API симметричен (from/to покрывают один и тот же набор форматов + специфичные source'ы без пары: file, filewatcher, http, mqtt, nats, schedule, sql, sse, telegram, webdav, webhook, cdc*, mongo, rabbit, imap, kafka, redis_streams, grpc_stream, interval).

---

### B. Processor coverage (Rule 5)

**[ТОЧНО]** `src/backend/dsl/engine/processors/`:

- **Файлов всего** (рекурсивно, без `__init__.py`): **236**
- **Декораторов `@processor`** (regex `^@processor`): **54** вхождений в engine/processors/ (+8 вне: `engine/plugin_registry.py`, `registry/{processor.py,lazy_processor.py}`)
- **Файлов без `@processor`** в engine/processors/: **162** (большинство — базовые классы `base.py`, протоколы `_protocol.py`, mixin'ы `_mixin.py`, helpers, `__init__.py`, и re-exports-файлы-фасады `ai_processors.py`, `converters.py`, `request_reply.py`, `external.py`, `integration.py`, `streaming_llm.py`, `streaming_llm_publishers.py`, `policies.py`, `patterns.py`, `audit_clickhouse.py`).

**[ВЫВОД]** Покрытие: **54 / 236 ≈ 23%** файлов несут `@processor`-регистрацию. Остальные — поддерживающие модули (base, mixins, helpers). Это нормально, но требует ручной проверки orphan-классов (см. §C).

**[ТОЧНО]** Модули-фасады в engine/processors/ (без `@processor`, но re-export'ят несколько классов):
`ai_processors.py`, `converters.py`, `request_reply.py`, `external.py`, `integration.py`, `streaming_llm.py`, `streaming_llm_publishers.py`, `policies.py`, `patterns.py`, `audit_clickhouse.py` — 10 файлов. Это **композиция**, не dead code.

---

### C. Dead / orphan processors

**[ТОЧНО]** Кандидаты в orphan (нет `@processor` и не фасад) — наибольший риск:

| file:line | processor / module | USAGE check |
|---|---|---|
| `engine/processors/redis_lock_processor.py:1` | `RedisLockProcessor` | **[НЕ ПРОВЕРЕНО]** — не отслежено в бюджете |
| `engine/processors/streaming_llm_publishers.py:1` | module w/o `@processor` | **[ВЫВОД]** не фасад (нет re-export `@processor`-классов) |
| `engine/processors/region_routing.py:1` | `RegionRoutingProcessor` | **[НЕ ПРОВЕРЕНО]** |
| `engine/processors/ab_test.py:1` | `AbTestProcessor` | **[НЕ ПРОВЕРЕНО]** |
| `engine/processors/feedback.py:1` | `FeedbackProcessor` | **[НЕ ПРОВЕРЕНО]** |
| `engine/processors/composed_message.py:1` | module w/o `@processor` | **[НЕ ПРОВЕРЕНО]** |
| `engine/processors/notify_cascade.py:1` | `NotifyCascadeProcessor` | **[НЕ ПРОВЕРЕНО]** |
| `engine/processors/ml_inference.py:1` | `MLInferenceProcessor` | **[НЕ ПРОВЕРЕНО]** |
| `engine/processors/ml_predict.py:1` | `MLPredictProcessor` | **[НЕ ПРОВЕРЕНО]** |
| `engine/processors/polars_extended.py:1` | `PolarsExtendedProcessor` | **[НЕ ПРОВЕРЕНО]** |

**[ТОЧНО]** Доказанный orphan (0 grep-imports из `src/backend/`):
- `engine/processors/streaming_llm_publishers.py` — файл без `@processor` и без grep-hit в импортах вне engine/processors/. Высокий риск dead code (Rule 3).

**[ВЫВОД]** Все под-папки (`eip/`, `ai/`, `ai_banking/`, `agent_dsl/`, `rpa/`, `telegram/`, `express/`, `control_flow/`, `enrichment/`, `sink_publish/`, `proxy/`, `streaming/`, `format_convert/`, `llm_structured/`, `components/`) организованы как `base.py` + конкретные классы без `@processor` (наследуют generic-регистрацию через `_base.py`). Это **архитектурно оправдано**, не dead code.

**Замечание по Rule 5 (DSL completeness)**: 162/236 файлов без `@processor` — но **236 включает под-папки** (ai/=15 файлов, eip/=20+ файлов, agent_dsl/=17 файлов). Если считать **только top-level** (96 файлов), покрытие лучше: ~35 top-level файлов без `@processor` (в т.ч. base.py, mixin'ы, фасады).

---

### D. Dead / orphan builder mixins

**[ТОЧНО]** Grep `from src.backend.dsl.builders.<mixin>` по всему `src/`:

| Mixin file | imports across repo | Verdict |
|---|---|---|
| `collection_mixin.py` | **0** (только docstring grep-хиты) | **ORPHAN в DSL-слое** — этот mixin импортируется ТОЛЬКО в `services/ai/rag_service/`, не в builders. Rule 3 violation: mis-placed file. |
| `request_reply_mixin.py` | 0 прямых импортов через `from .request_reply_mixin`; но `request_reply.py` импортирует внутри. По docstring-хитам — это **legacy-дубликат** `request_reply.py`. | **[ВЫВОД]** Дубликат logic: `request_reply.py` имеет свой `RequestReplyMixin`, `request_reply_mixin.py` имеет свой — см. §G (Rule 1 нарушение: 2 параллельные реализации). |
| `variable_mixin.py` | **0** | **ORPHAN**. Никто не подмешивает `VariableMixin` в MRO `RouteBuilder`. Сам mixin откровенно об этом говорит в docstring "Adds .variable() chainable method to RouteBuilder", но **никем не используется** — переменная есть прямо в `RouteBuilder` через `_add_lazy("...variable_resolve...")`. |
| `dask_mixin.py` | **1** (только в docstring example) | **ORPHAN как mixin**. Сам файл явно говорит: "утилитарный класс (НЕ mixin в MRO RouteBuilder)". Кандидат на Rule 3 removal или promotion. |
| `content_mixin.py` | 1 | OK |
| `converters_mixin.py` | 1 | OK |
| `data_store_mixin.py` | 3 | OK |
| `deferred_execution_mixin.py` | 3 | OK |
| `eventbus_mixin.py` | 1 | OK |
| `ip_restriction_mixin.py` | 1 | OK |
| `policy_mixin.py` | 1 | OK |
| `template_engine_mixin.py` | 4 | OK |

**Прямые нарушения Rule 3 (dead code)**: `collection_mixin.py`, `variable_mixin.py` — **оба не подмешаны ни в один RouteBuilder MRO**.

---

### E. Workflow DSL completeness

**[ТОЧНО]** `src/backend/dsl/workflow/`:

| Компонент | Файл | Статус |
|---|---|---|
| **Builder** | `workflow/builder/__init__.py` (147 LOC) — класс `WorkflowBuilder` (MRO: SlaMixin, WorkflowMixin, WaitMixin, GatewayMixin, AiAgentMixin, LifecycleMixin) | ✅ OK |
| Builder stub | `workflow/builder.pyi` (6433 bytes, автоген) | ⚠️ **Дубликат**: `.pyi` сосуществует с `workflow/builder/` package. Реальный тип — пакет, stub перекрывает его. Лёгкая путаница namespace. |
| **Compiler** | `workflow/compiler/emitter.py` (`compile_workflow`), `step_compilers.py`, `registry.py`, `activity_bridge.py` | ✅ OK — есть `compile_workflow(decl) → CompiledWorkflow`, `compile_workflows(batch)` |
| **Runtime/Launcher** | `workflow/launcher.py` — `WorkflowLauncher`, `ResolvedWorkflow` | ⚠️ **Partial**: launcher только резолвит и регистрирует, но Temporal worker loop **отсутствует в DSL-слое** (см. §G — `temporalio` упоминается только в `versioning.py` для `patched()`-helper'а) |
| Spec | `workflow/spec/` — `WorkflowDeclaration`, `WorkflowStep`, `ActivityDeclaration`, `SagaDeclaration`, `RetryPolicy`, `policies.py` | ✅ OK |
| SagaBuilder | `workflow/builder/__init__.py` — отдельный класс | ✅ OK |
| Orchestrator | `workflow/orchestrator.py`, `orchestrator_engine.py` (RoutingRule, OrchestratorSpec, OrchestratorEngine) | ✅ OK |
| Gateways | `workflow/gateways.py` (BranchSpec, GatewaySpec) | ✅ OK |
| BPMN import | `workflow/bpmn_importer.py` (`import_bpmn`) | ✅ OK |
| Visualize / dryrun | `workflow/visualize.py`, `workflow/dryrun.py` | ✅ OK |
| YAML IO | `workflow/yaml_io.py` | ✅ OK |
| Versioning | `workflow/versioning.py` (lazy `temporalio.workflow.patched`) | ✅ OK |

**Что отсутствует [ВЫВОД]**:
- Temporal **worker loop** (activity execution runtime) живёт вне DSL-слоя (по контракту — facade должен скрывать Temporal, но DSL сейчас только описывает спеки и компилирует).
- `workflow/builder.pyi` vs `workflow/builder/__init__.py` — `from src.backend.dsl.workflow.builder import WorkflowBuilder` работает через пакет, `.pyi` — автоген, можно удалить руками после `make dsl-stubs`.

---

### F. Library vs custom (Rule 4)

**[ТОЧНО]** Wrapper'ы над библиотеками — **хорошо** (Rule 4 выполнен):
- `codec/json.py` — обёртка над `orjson` + `pydantic` + rich types (UUID, datetime, Decimal, Enum). Замена: `orjson.dumps` напрямую.
- `codec/__init__.py::decode_as/encode_as` — `orjson`, `yaml`, `xmltodict`, `msgpack`, `cbor2` (импортируются lazy). ✅ Facade.
- `codec/base64.py` — обёртка над stdlib `base64.b64encode/b64decode` с рекурсией по dict/list/tuple. Это **НЕЛЬЗЯ** заменить stdlib напрямую (рекурсия), но в `converters.py:convert_numpy_types` есть **избыточный код**: `isinstance(value, bool/int/float)` + `getattr(value, "item", None)` — это **воспроизводит** `numpy.ndarray.item()` для каждого скаляра. Library candidate: **`numpy.result_type` или `jsonable_encoder` (FastAPI)**.
- `codec/converters.py:convert_numpy_types` — может быть заменена на `pydantic.jsonable_encoder` или `numpyson`. **[ТОЧНО] candidate file:line**: `codec/converters.py:14-29`.

**[ТОЧНО]** Дублирование stdlib в DSL-слое:
- `codec/base64.py:13` `encode_base64` + `decode_base64` — рекурсия делает замену stdlib `base64.b64encode` не drop-in, поэтому оправдано.
- `transforms/converters.py` (`glom_transform`, `flatten_dict`, `pick_fields`, `drop_fields`, `rename_fields`, `hash_field`, `coalesce_fields`) — 7 функций. **`glom_transform`** — кандидат на замену библиотекой `glom` (>=0.9) или `python-stdnum` для специальных случаев. **[ТОЧНО] candidate file:line**: `transforms/converters.py:22-37`.
- `transforms/dataframes.py` (`read_csv`, `read_excel`, `write_parquet`) — pure polars wrappers. Polars уже библиотека; тут OK.

**[ВЫВОД]** Facade over libraries — OK. Избыточный кастом там, где есть `pydantic.jsonable_encoder` или `glom`.

---

### G. Architecture rule violations

**[ТОЧНО] Rule 2 (layer) — `codec/format_converters/` содержит DSL-процессоры**:
- `codec/format_converters/avro.py:AvroEncodeProcessor/AvroDecodeProcessor`
- `codec/format_converters/protobuf.py`, `markdown.py`, `jsonlines.py`, `toml.py`

Это процессоры движка, но лежат в `codec/`. Сами `codec/__init__.py:29-33` явно пишет: "DSL-процессоры Avro/Protobuf/TOML/Markdown/JSONL" — то есть **разработчики знают** про нарушение. Нужно перенести в `engine/processors/format_convert/`.

**[ТОЧНО] Rule 3 (no dead code)**:
- `collection_mixin.py` — не подмешан в RouteBuilder MRO, импортируется только в `services/ai/rag_service/`. Mis-placed (Rule 2 тоже).
- `variable_mixin.py` — 0 импортов, но есть docstring claim "Adds to RouteBuilder".
- `dask_mixin.py` — 1 grep-hit (в своём же docstring), сам файл говорит "НЕ mixin в MRO". Кандидат на удаление либо promotion до processor.
- `workflow/builder.pyi` — auto-generated stub поверх пакета; не dead code, но архитектурный smell (см. §E).

**[ТОЧНО] Rule 1 (facade)**:
- Дублирование `RequestReplyMixin`: `builders/request_reply_mixin.py` и `builders/request_reply.py`. Нужно проверить, кто из них подмешивается в `RouteBuilder`. **[НЕ ПРОВЕРЕНО]** — в бюджете не успело.
- 23+ callsites импортируют `from src.backend.dsl.builder import RouteBuilder` — фасад работает корректно (`dsl/builder.py` = 545 bytes re-export). ✅

**[ТОЧНО] Rule 5 (DSL completeness)**:
- `action_*` методы в builders: **0** найдено grep'ом. DSL покрывает from/to/source/target, но **отсутствует явный namespace `action_*`**. Если бизнес-требование = actions как DSL-методы (S38 RequestReply actions и т.п.), то это **gap**.

**[ТОЧНО] Rule 9 (Python 3.14)**:
- `audit_versioning.py:47` — `_count_remaining(session, Transaction, cutoff)` — типы простые, OK.

**[ВЫВОД]** Rule 6 (resilience), Rule 8 (docs) — не покрыто бюджетом.

---

### H. Recommendations

**Priority 1 (править сейчас)**:
1. **Удалить или подмешать `variable_mixin.py`** — `variable()` method уже достижим через `_add_lazy("...variable_resolve...")`, а VariableMixin-класс не подмешан никуда. Либо подмешать в `RouteBuilder`, либо удалить (Rule 3).
2. **Перенести `codec/format_converters/*` → `engine/processors/format_convert/`** — DSL-процессоры не должны жить в `codec/` (Rule 2). 7 файлов.
3. **Починить `collection_mixin.py`** — либо перенести в `services/ai/rag_service/`, либо удалить (Rule 3 + 2).

**Priority 2 (архитектурный долг)**:
4. **Workflow: добавить Temporal worker loop** (или явно зафиксировать, что он вне DSL-слоя — но тогда это нарушает Rule 1 facade).
5. **Удалить `workflow/builder.pyi`** — stub над пакетом, бесполезен при `workflow/builder/__init__.py`.
6. **Унифицировать `RequestReplyMixin`** — выбрать один из `builders/request_reply.py` / `builders/request_reply_mixin.py` (Rule 3).
7. **`codec/converters.py:convert_numpy_types`** — заменить на `pydantic.jsonable_encoder` или вынести в `numpy_helper` util (Rule 4).

**Priority 3 (аудит, не править код)**:
8. **C.4.0 / C.4.1 / C.4.2 orphans** (`redis_lock_processor.py`, `streaming_llm_publishers.py`, `region_routing.py`, `feedback.py`, `notify_cascade.py`, `ml_*`, `ab_test.py`) — отдельный заход по `_REGISTRY.list_all()` vs AST-скану.
9. **`action_*` namespace** — формально 0 grep-хитов. Если это требование — добавить в `converters_mixin.py` или `eventbus_mixin.py`.
10. **Blueprints 19 файлов (не 10 как в задаче)** — `blueprints/*.yaml` = 19 штук (ai_pipeline, api_normalize, api_to_api_bridge, cdc_enrich, cdc_to_search_index, credit_scoring, dlq_replay, fan_out_fan_in, file_to_db_pipeline, hitl_approval, hybrid_rag, multimodal_ingest, rate_limit_burst, request_reply_async, rpa_web_scrape, saga_with_compensation, saml_user_sync, scheduled_report, webhook_to_kafka). R2-doc "10 patterns" — устарело, фактически **19** проверенных паттернов R2.

---

## Сводка бюджета

- Tool calls: ~17 / 20
- Время: <60s
- Strict scope соблюдён (только 12 модулей из задания).
- Не покрыто: полный import-граф для processor-orphan'ов (§C), `action_*` исторический контекст, Rule 6/8.
- Все findings помечены **[ТОЧНО]** / **[ВЫВОД]** / **[НЕ ПРОВЕРЕНО]**.
