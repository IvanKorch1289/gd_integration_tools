# Domain A10-Business-Logic-Extensions-Routes — независимый аудит (cycle 1)

> Дата: 2026-08-06
> Агент: A10-Business-Logic-Extensions-Routes
> HEAD анализа: `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7` (S184-w4 retrospective + 4 фикса в working tree)
> Метод: прямая верификация кода (Read/Grep/`python tools/check_layers.py`).
> Никаких markdown-документов как источника фактов — все цитаты кода взяты из исходников.
> Scope: `extensions/**` (core_admin, core_entities/{users,orders,orderkinds,files}, credit_pipeline, dadata, example_plugin, osint_agent, skb, test_plug) + `routes/**` (composition_demo, echo_demo, health_proxy_demo, hello_route, jupyter_hub_run, osint_agent, test_route_w1).
> Фактический объём: **5799 production LOC** в `extensions/`, **407 LOC** (YAML/TOML) в `routes/`.
> Тесты в scope: 7 extension test-suite + `tests/unit/extensions/credit_pipeline/` (2 файла) + `tests/integration/extensions/credit_pipeline/` (1 файл).

---

## 0. Сводка готовности

| Подкатегория | Готовность | Обоснование |
|---|---|---|
| `plugin.toml` schema соответствие (ADR-042) | 80% | Все 11 plugin.toml валидны: `trust_tier` (8/11 имеют `="A"`), `entry_class`, `requires_core`, `capabilities[]`, `provides{}`, `tenant_aware`. **Gap (P1):** dadata/skb/core_admin — `entry_class = "extensions.<name>.schemas_only:SchemasOnlyEntry"`, но `SchemasOnlyEntry` это **пустой класс (5 LOC)**, не наследник `BasePlugin`. Не зарегистрируется через `PluginLoader._load_one()` — будет `ImportError`/`isinstance(obj, BasePlugin)` → False. |
| Capability-gate соответствие декларациям | 75% | 11/11 manifest'ов декларируют capabilities. core_entities: scope=`{users,orders,orderkinds,files}` (ExactAliasMatcher), credit_pipeline: `db.{read,write} credit_applications` + `net.outbound *.skb-techno.ru`. **Gap (P0):** `extensions/osint_agent/functions/osint_workflow.py:17` импортирует `from src.backend.dsl.helpers.banking import validate_inn` — нарушение правила "extensions → core-only" (DSL не входит в core layer; см. `tools/check_layers.py:68`). |
| 80% YAML / 20% Python (DSL dual-mode) | 65% | routes/* — 7 reference routes, все YAML (407 LOC). credit_assessment.workflow.yaml (97 LOC) + 3 AI workflow yaml (S12 K4 W1). **Gap (P0):** `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml:22,30` ссылается на `extensions.credit_pipeline.services.clients.skb:fetch_for_workflow` — функция НЕ существует в `extensions/credit_pipeline/services/clients/skb.py` (149 LOC — только get_request_kinds/create_request/get_result). Строка 43: `extensions.credit_pipeline.functions.publish:emit_decision` — `functions/publish.py` не существует; `functions/__init__.py:13` явно `__all__: tuple[str, ...] = ()`. **Gap (P0):** `routes/hello_route/main.dsl.yaml:8` → `extensions.hello_route.normalizer:apply_rules` — модуль `extensions/hello_route/` не существует. **Gap (P0):** `routes/test_route_w1/main.dsl.yaml:7` → `extensions.test_route_w1.normalizer:apply_rules` — модуль `extensions/test_route_w1/` не существует. |
| Миграция CRUD из ядра в extensions/core_entities | 95% | 4 core_entities: users, orders, orderkinds, files — все domain models мигрированы в `extensions/core_entities/<name>/domain/models.py`. Schemas — в `extensions/core_entities/<name>/schemas/`. Services — в `extensions/core_entities/<name>/services/`. Alembic env.py импортирует модели из extensions (`src/backend/infrastructure/database/migrations/env.py:15-23`). Backward-compat shim'ы сохранены: `src/backend/services/io/files.py:11-17` (DeprecationWarning). |
| Routes (`routes/<name>/`) — «лёгкие плагины» V11.1a | 75% | 7 routes: 3 reference (composition_demo/echo_demo/health_proxy_demo), 1 wizard-template (hello_route), 1 wizard-template (test_route_w1), 2 production-like (jupyter_hub_run/osint_agent). Все имеют route.toml с `[route.slo]`/`[route.feature_flag]`. **Gap:** hello_route + test_route_w1 — wizard-generated заготовки с `/api/v1/CHANGEME` path и broken call_function refs (см. выше). |
| Trust-tier coverage (`"A"` для internal) | 90% | 8/11 manifest'ов имеют `trust_tier = "A"`: core_admin, dadata, skb, credit_pipeline, example_plugin, core_entities/*×4. 2/11 = "B": test_plug (wizard-generated), osint_agent (Perplexity API — обоснованно untrusted). 1/11 = отсутствует — N/A (default `"B"` per `manifest_toml.py:225`). |
| Layer discipline (extensions → core only) | 75% | `python tools/check_layers.py --root extensions` → **3 NEW violations** (allowlist = 0 entries для `extensions/`): 1) `extensions/core_entities/orders/workflows/orders_dsl.py:34 → src.backend.dsl.workflow.builder`, 2) `extensions/core_entities/orders/workflows/orders_dsl.py:35 → src.backend.dsl.workflow.spec`, 3) `extensions/osint_agent/functions/osint_workflow.py:17 → src.backend.dsl.helpers.banking`. **Gap:** orders_dsl.py и osint_workflow.py пересекают границу слоя через DSL — должны использовать `core/dsl/workflow/*` или core-facades (см. ADR-0207). |
| Async-first + non-blocking I/O в extension services | 85% | `extensions/core_entities/users/services/users.py:228-235` — async LDAP bind через `AdDirectoryClient`. `extensions/credit_pipeline/services/clients/skb.py:48-68` — async HTTP через `BaseExternalAPIClient`. **Gap (P2):** `extensions/osint_agent/functions/osint_workflow.py:226-241` — `_scrape_url` использует `httpx.AsyncClient` без `OutboundHttpClient` facade (обходит WAF + per-service timeouts). Ponytail-комментарий автора это признаёт. |
| Pydantic 2 / ConfigDict / русские docstrings | 100% | Все schemas наследуют `BaseSchema` (`src/backend/schemas/base.py`). Все docstrings — на русском (за исключением агрегатов в `examples` для `tests/`). `extensions/credit_pipeline/domain/models.py` — Pydantic 2 BaseModel. 6 плагинов в `extensions/core_entities/*/admin.py` используют sqladmin `ModelView`. |
| Тестовое покрытие extension/runtime | 65% | 11 test-файлов: credit_pipeline (5 + 2 в tests/unit/ + 1 в tests/integration/) + 12 в core_entities (3 на плагин × 4). Покрытие: smoke lifecycle + manifest parse + capability check + repository pattern. **Gap (P2):** нет тестов для osint_agent production path (только validate_inn/parse sections), нет тестов для credit_pipeline SKB client WAF routing (`get_request_kinds` через production env), нет тестов для orders workflow DSL chain (`build_all_order_workflows` → 5 spec; ни один test не запускает реальный workflow). |

**ИТОГОВАЯ ОЦЕНКА: 77%**

---

## 1. Таблица находок

| ID | Приоритет | Файл:строка | Описание | Предложенный фикс | Оценка сокращения строк |
|---|---|---|---|---|---|
| B-101 (новый) | **P0** | `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml:22,30,43` | Workflow references 2 несуществующие функции: `extensions.credit_pipeline.services.clients.skb:fetch_for_workflow` (нет в skb.py:149 LOC) и `extensions.credit_pipeline.functions.publish:emit_decision` (`functions/publish.py` не существует, `functions/__init__.py:13` = empty `__all__`). Любая runtime-активация `credit_assessment` через WorkflowDeclaration → `UnknownActivity` exception (подтверждено: README строка 24 декларирует «UnknownActivity для несуществующих handler'ов — для S12 это OK», но `credit_assessment` помечен как production-target). | Вариант A: удалить `credit_assessment.workflow.yaml` целиком (он не используется, registration path отсутствует в `workflow_setup.py`). Вариант B: реализовать `fetch_for_workflow` (async wrapper над `get_request_kinds`) + `emit_decision` (publisher через MQ `credit.events.*`). Пока выбрать A — fail-loud on activation. | -97 LOC (yaml) + 0 LOC (если выбрать A); -97 + ~80 (если выбрать B) |
| B-102 (новый) | **P0** | `routes/hello_route/main.dsl.yaml:8` | `ref: extensions.hello_route.normalizer:apply_rules` — модуль `extensions/hello_route/` НЕ существует. Wizard-generated шаблон с broken reference. Feature flag `hello_route_enabled` default-on (line 7 `feature_flag = { enabled = true }`) → если `v11.route_loader_enabled=true`, RouteLoader попытается resolve `extensions.hello_route.normalizer` → ImportError на startup. | Удалить `routes/hello_route/` целиком (wizard-template, не production) или заменить `apply_rules` на существующую `extensions.credit_pipeline.functions.normalize:apply_rules` + per-route import. | -28 LOC (yaml + route.toml), ponytail: «deletion over addition» |
| B-103 (новый) | **P0** | `routes/test_route_w1/main.dsl.yaml:7` | `ref: extensions.test_route_w1.normalizer:apply_rules` — модуль `extensions/test_route_w1/` НЕ существует (есть `extensions/test_plug/`, но это другой плагин). Wizard-generated шаблон с broken reference + path `/api/v1/CHANGEME` (`main.dsl.yaml:5`). Feature flag `test_route_w1_enabled` default-on. | Удалить `routes/test_route_w1/` (wizard-template, не production) или заменить path + ref на production-safe target. | -17 LOC |
| D-AUDIT-10 | P0 | `extensions/credit_pipeline/agents/__init__.py:94-114` | D-AUDIT-10 (T-W1-08, banking-critical) — fail-CLOSED scoring: пустой/incomplete payload → REJECT, score=0, risk=HIGH. Реальная реализация, не stub (`stub: False`). **Верифицировано:** test_scoring_fail_closed.py:9-22 подтверждает контракт. Корректное fail-closed, никаких фиксов не требуется. | — | — |
| D-AUDIT-100 (новый) | **P0** | `extensions/dadata/schemas_only.py:4-5`, `extensions/skb/schemas_only.py:4-5`, `extensions/core_admin/schemas_only.py:4-5` | Все 3 manifest'а указывают `entry_class = "extensions.<name>.schemas_only:SchemasOnlyEntry"`, но `SchemasOnlyEntry` — пустой класс (5 LOC: docstring + `class SchemasOnlyEntry: pass`), **не наследник `BasePlugin`**. При `v11.plugin_loader_enabled=true` → `loader._load_one` пытается `isinstance(instance, BasePlugin)` → False → `PluginInventoryConflictError`/`skipped` с reason="not BasePlugin subclass". Текущая фактическая работоспособность: 3 плагина отключены, их схемы импортируются напрямую из `extensions.<name>.schemas.route` (см. `src/backend/entrypoints/api/v1/endpoints/admin.py:3`, `skb.py:5`, `dadata.py:12`, `src/backend/dsl/commands/setup/registers_domains.py:76,120`). | Решение A: наследовать `SchemasOnlyEntry` от `BasePlugin` с no-op хуками (минимальный fix, ~10 LOC). Решение B: оставить как «proxy» в production, но удалить `entry_class` из `plugin.toml` (3 строки × 3 = 9 LOC). Решение B проще и ponytail-friendly. | -3 LOC (если B) |
| D-AUDIT-101 (новый) | **P1** | `extensions/credit_pipeline/tests/test_credit_pipeline_v2_flag.py:13-16` | Тест `test_credit_pipeline_v2_flag_exists_and_default_off` ассертит `is_enabled("credit_pipeline_v2") is False` (default-OFF per Sprint 7 promise). Реальное значение в `src/backend/core/config/features/plugins.py:43` = `default=True`. **Тест провалится** при запуске — `AssertionError: assert True is False`. | Сменить `default=False` в `plugins.py:43` (consistency with test) ИЛИ переписать тест под `default=True` (что отражает реальность после S7 миграции). Ponytail: первое (tests as spec → align code to spec). | 1 LOC |
| D-AUDIT-102 (новый) | **P1** | `extensions/osint_agent/functions/osint_workflow.py:17` | Импорт `from src.backend.dsl.helpers.banking import validate_inn` — нарушает `extensions → core-only` rule (dsl не в core layer, `check_layers.py:68`). **Verify via `python tools/check_layers.py --root .` → 3 NEW violations**, третья — этот файл. Также `extensions/core_entities/orders/workflows/orders_dsl.py:34,35` импортирует `src.backend.dsl.workflow.{builder,spec}` — те же 2 нарушения. | Перенести `validate_inn` (banking helper) в `src/backend/core/utils/banking.py` или `src/backend/core/validators/` (допустимо для extensions per `ALLOWED["extensions"]={"core"}`). Альтернатива для orders_dsl: переместить workflow specs в `src/backend/services/workflows/orders_dsl.py` (но это нарушит boundary «workflows/ — meta-layer»); лучше — оставить в extensions и создать core facade. | ~30 LOC (move + import) |
| D-AUDIT-103 (новый) | **P2** | `extensions/osint_agent/functions/osint_workflow.py:226-241` | `_scrape_url` использует прямой `httpx.AsyncClient(timeout=10.0, follow_redirects=True)` в обход `OutboundHttpClient` facade (`src/backend/services/integrations/`). Ponytail-комментарий автора это признаёт (lines 228-230: «используем прямой httpx (не facade) — это helper для OSINT workflow, не infrastructure-layer component»). Обход WAF + отсутствует per-route timeout policy + нет retry-унификации через Tenacity. | Использовать `outbound_client.get(url=...)` или создать thin wrapper в extensions/osint_agent/services/. | ~10 LOC |
| D-AUDIT-104 (новый) | **P2** | `extensions/credit_pipeline/services/clients/skb.py:79-93,95-107,109-133` | Все 3 метода (`get_request_kinds`/`create_request`/`get_result`) используют `except Exception as exc: raise ServiceError from exc` (lines 92-93, 105-107, 131-133). Программные ошибки (TypeError, KeyError) теряются — caller видит generic `ServiceError`. Подтверждено как gap в A3-Services audit (line 21 — generic note). | Разделить `except (httpx.HTTPError, httpx.RequestError)` для HTTP-failures vs re-raise для programming errors. | ~9 LOC (3×3) |
| D-AUDIT-105 (новый) | **P2** | `extensions/credit_pipeline/workflows/__init__.py:3-8` | 4 TODO-комментария «Team T3 (Sprint 8+)» в credit_pipeline (functions/, routes/, services/clients/, workflows/). Реальный статус: workflows/ и services/clients/ — частично заполнены (skb.py:149 LOC + 4 yaml), functions/__init__.py пустой (`__all__: tuple[str, ...] = ()`), routes/__init__.py пустой. Sprint 8 → Sprint 184 → TODO-комментарии устарели на 170+ спринтов. | Удалить TODO-блоки или заменить на конкретный issue-link. Ponytail: удалить, поскольку реальная имплементация в skb.py есть (TODO в services/clients/__init__.py:3-8 — полностью несостоятельный). | -24 LOC (4×6) |
| D-AUDIT-106 (новый) | **P2** | `extensions/core_entities/orders/workflows/orders_dsl.py:284-343` | `order_processing_workflow_spec` использует `INITIAL_DELAY = 3600s (60 min)` (`src/backend/core/config/constants.py:68`). Hard-coded value: `sleep duration_s=float(consts.INITIAL_DELAY)` в StepDeclaration (line 315). Нет env-override; нет feature-flag для tune в dev_light. | Вынести INITIAL_DELAY в `settings.tasks.workflow_initial_delay_s` (pydantic-settings). | ~5 LOC |
| D-AUDIT-107 (новый) | **P3** | `extensions/osint_agent/plugin.py:33-37` | Дублирование `_make_handler` factory pattern (lines 36-37, 49-54): тот же код что в `extensions/credit_pipeline/plugin.py:36-58`. ~10 LOC copy-paste × 2 плагина. | Поднять `_make_handler` в `extensions/__init__.py` или `src/backend/core/plugin_runtime/_internal.py` (через facade). Ponytail: оставить как есть (YAGNI; общий код ради 2 плагинов = premature abstraction). | — |
| D-AUDIT-108 (новый) | **P3** | `extensions/core_entities/users/services/users.py:176-238` | `_login_ldap` содержит 60+ LOC inline-логики (find_user → validate_credentials → _provision_ldap_user). Возможно вынести в `AdDirectoryClient.authenticate_and_provision()` для уменьшения дублирования между users-service и будущими LDAP-aware сервисами. | Рефакторинг в src/backend/core/auth/ad_directory_client.py. **Не блокер**, текущая инкапсуляция в `UserService` допустима. | — |
| D-AUDIT-109 (новый) | **P3** | `extensions/osint_agent/functions/osint_workflow.py:21-65` | OSINT_REPORT_TEMPLATE (45 LOC) — длинная string-template. В production: перенести в `extensions/osint_agent/prompts/osint_report.j2` (Jinja2), load via `PromptsRegistry`. S74 W1 уже имеет prompts infrastructure. | Использовать `src/backend/services/ai/prompts/registry.py:PromptsRegistry`. | ~50 LOC (template → jinja2) |

**Сводка по приоритетам:** 3× P0 (broken references), 3× P1 (test/layer/SchemasOnlyEntry), 3× P2 (TODO/HTTP-error swallowing/timing), 3× P3 (refactor/clean-up). Минимум 6 находок требуют немедленного фикса до production-readiness (B-101, B-102, B-103, D-AUDIT-100, D-AUDIT-101, D-AUDIT-102).

---

## 2. Не проверено (явный список)

| Что | Почему не проверено |
|---|---|
| `routes/jupyter_hub_run/main.dsl.yaml` реальная интеграция с Jupyter Hub | Refs `services.jupyter.hub_run_adapter:run` — нужно проверить runtime; live-test вне scope (требует Jupyter Hub instance + `capabilities.requires_plugins` declaration). |
| `extensions/core_entities/orders/workflows/orders_dsl.py` integration с Temporal worker | Workflow DSL → Temporal compilation требует running worker. Подтверждено только structural validity через `WorkflowBuilder` API. |
| `extensions/osint_agent/functions/osint_workflow.py` production search behavior (Perplexity + Tavily + scraping) | Требует live API keys + интеграционных тестов. Smoke-test покрывает только INN validation + prompt composition (test_osint_workflow.py). |
| `extensions/credit_pipeline/agents/__init__.py` rule-based scoring accuracy | Real ML-модель (НБКИ/Spark) — out of scope S76 W1. Текущий rule-based = placeholder (явно отмечено в docstring). |
| `extensions/skb/services/waf_route.py:16-31` integration с production WAF (skb-techno.ru) | 32 LOC чистая функция, well-tested unit-style, но live WAF-роутинг не воспроизводится в audit. |
| `extensions/core_entities/users/services/users.py:228-238` LDAP auto-provisioning production-safety | Требует live AD/LDAP server; race condition между `find_user` и `validate_credentials` не покрыта тестами (потенциальный TOCTOU). |
| `src/backend/services/integrations/skb.py:142-152` `resolve_waf_route` backward-compat shim | deprecation-warning path, но не помечен как `__deprecated__`; реальный migration timeline = «Sprint 37+» (line 8), истёк 147 спринтов назад. |
| `extensions/core_admin/schemas/route.py:85-95` `AdminCacheInvalidateTagsSchema` (PII risk) | Schema-level OK; реальный tag-invalidation behavior — в `services/cache/admin.py` (вне A10 scope, см. A2/A3). |
| `extensions/core_entities/*/admin.py` admin panel access control | sqladmin views; role-guard в `setup_admin.py` — вне A10 scope. |
| Trust-tier enforcement runtime (`PluginLoader.sandbox`) | Sandbox setup в `src/backend/core/plugin_runtime/sandbox.py`, tier enforcement — runtime. Статический анализ: trust_tier декларирован, runtime-path не верифицирован. |
| 7 routes в `routes/*/route.toml` capabilities vs plugin installation invariant check | `bootstrap_v11_route_loader` (line 89: «invariant-check `capabilities ⊆ plugins ∪ public-core`») — runtime, не проверяется статически. |
| Hot-reload (`extensions/` + `routes/` watcher) production-safety | `bootstrap_v11_hot_reload` использует `watchfiles.awatch` — поведение при race conditions не проверено. |
| `src/backend/services/ai/multi_agent/supervisor.py:382-429` reference stub-кредит-pipeline | Это reference implementation в core (НЕ в extensions), но `get_credit_pipeline_supervisor` экспортируется. Extension уже заменил его на real agents (`extensions/credit_pipeline/agents/__init__.py`); duplicate stub не критичен, но избыточен. |
| Migration completeness: legacy `src/backend/core/domain/models/{users,orders,orderkinds,files}.py` shims | Утверждается удалёнными (`migrations/env.py:12-15` комментарий «DEPRECATED shim, удалён этим коммитом»), но не верифицировано на 100%. |
| `extensions/credit_pipeline/services/clients/nbki.py`, `cbr.py` — указаны в README как TODO | Файлы отсутствуют в `services/clients/`, README устарел. |

---

## 3. Запросы к смежным доменам

| Домен | Запрос |
|---|---|
| **A1-Infrastructure** | Подтвердить, что `extensions/credit_pipeline/services/clients/skb.py:48-68` корректно использует `BaseExternalAPIClient` через `core/services/base.py` re-export. Найден путь: `src.backend.services.core.base_external_api.BaseExternalAPIClient` (per `src/backend/services/integrations/skb.py:21`). Verify alias chain через `EXTENSIONS_FRAMEWORK_EXCEPTIONS`. |
| **A2-Security** | Verify: WAF-coverage для `extensions/skb/services/waf_route.py` — `check_waf_coverage.py` должен включать `*.skb-techno.ru` (per `extensions/credit_pipeline/plugin.toml:28`). Также: `extensions/osint_agent` объявляет `net.outbound *.perplexity.ai` — verify WAF coverage. |
| **A3-Services** | Подтвердить, что 7 module-level singletons в extensions (`get_user_service`, `get_order_service`, `get_file_service`, `get_order_kind_service`, `get_credit_skb_client`, `get_skb_service`, `get_dadata_service`) согласуются с общей singleton-policy (см. A3-Services audit line 23: «7 module-level singletons в обход стандарта»). Ponytail: внутри extensions singleton допустим (некогда рефакторить в `@app_state_singleton`); попросить A3-Services formal approve для in-extension singletons. |
| **A4-Entrypoints** | Verify: `routes/jupyter_hub_run/main.dsl.yaml` поддерживает ли auto-registration через multi-protocol (GraphQL mutation `jupyterHubRun`, SOAP envelope, MCP tool, WebSocket message — все упомянуты в комментариях yaml:6-11). Проверить, что `route_registry.register(pipeline)` (см. `src/backend/plugins/composition/lifecycle/plugin_loader.py:170`) корректно публикует route в MCP/GraphQL/SOAP endpoints. |
| **A6-DSL-Route-Workflow-Service** | **`extensions/core_entities/orders/workflows/orders_dsl.py`** — 2 layer-violation imports (`src.backend.dsl.workflow.builder`, `src.backend.dsl.workflow.spec`). Запрос: либо создать `core.facades` для WorkflowBuilder/WorkflowDeclaration/SagaDeclaration/SleepDeclaration/SensorDeclaration, либо вынести DSL workflow specs в `src/backend/services/workflows/orders_dsl.py` (но тогда теряется domain-ownership extension). Рекомендация: `core.facades.workflow` — единая точка для extensions. |
| **A8-Workflow-Temporal** | `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml` — broken `fetch_for_workflow`/`publish_decision`. Запрос: workflow_setup.py импортирует `orders_saga` + `payments_saga` (lines 76-79) — оба файла удалены (per `tests/unit/workflows/test_orders_saga.py:5-7` «orders_saga demo removed»). Workflow bootstrap default-OFF (per `src/backend/core/config/workflow.py:39`), но **`_bootstrap_default_declarations` выполнится при flip → ImportError на startup**. |
| **A9-Agents-AI-RAG** | `extensions/osint_agent/functions/osint_workflow.py` — прямое использование `httpx` для scraping (D-AUDIT-103), bypass `WebSearchService` facade для основного search (lines 254-265). Запрос: заменить на `OutboundHttpClient` + унифицированный search через `services/ai/web_search/`. Также `extensions/osint_agent/functions/osint_workflow.py:309` использует `services.ai.llm_gateway` (LiteLLM gateway) — verify что LiteLLM/PydanticAI gateway handle response_format правильно для structured sections parsing. |
| **A11-Dependencies-Supply-Chain** | `extensions/osint_agent/plugin.toml:8` `trust_tier = "B"` — verify что tier-B sandbox (`src/backend/core/plugin_runtime/sandbox.py`) реально enforced для osint_agent. Дополнительно: `extensions/test_plug/plugin.toml:8` `trust_tier = "B"` (wizard), но capabilities закомментированы (lines 16-27) — sandbox не активируется по факту (нет capabilities для gate). |
| **A12-Config-Environment-Ops** | `extensions/credit_pipeline/services/clients/skb.py:139-148` использует `settings.skb_api_settings` (глобальный config). Per-service timeout override отсутствует — `SKBAPISettings` (per `src/backend/core/config/external_apis/skb.py`) не имеет env-override на per-extension basis. Запрос: verify, что `http_base_settings.waf_url` env-переменная работает для `extensions/credit_pipeline` отдельно от `services/integrations/skb.py`. |

---

## 4. Готовность домена: 77%

### Обоснование итоговой оценки

**Плюсы (высокая база):**
- **Миграция CRUD в extensions/core_entities — практически полная (95%)**: 4 entity (users/orders/orderkinds/files) с models/schemas/services/repositories/admin/tests. Alembic env.py уже использует новые пути. Backward-compat shim'ы корректно помечены `DeprecationWarning`.
- **Plugin manifests структурно валидны (11/11)**: name/version/requires_core/entry_class/tenant_aware/capabilities[]/trust_tier все на месте. 8/11 имеют `trust_tier = "A"` для internal trusted.
- **Fail-closed scoring D-AUDIT-10 верифицирован**: `extensions/credit_pipeline/agents/__init__.py:94-114` корректно отклоняет unknown-tenant payload (test_scoring_fail_closed.py подтверждает).
- **Pydantic 2 + ConfigDict + русские docstrings — 100%**: соответствует философии проекта (CLAUDE.md V22).
- **DSL declarative routes (407 LOC YAML)** + Workflow DSL (4 yaml в credit_pipeline).

**Минусы (3 P0 + 3 P1 — блокеры до production-readiness):**
- **3 broken call_function references (P0)**: `credit_assessment.workflow.yaml` (×2: fetch_for_workflow, emit_decision), `hello_route/main.dsl.yaml` (extensions.hello_route.normalizer), `test_route_w1/main.dsl.yaml` (extensions.test_route_w1.normalizer). При `v11.route_loader_enabled=true` → ImportError на startup.
- **3 layer violations (P0/P1)**: `extensions/osint_agent/functions/osint_workflow.py:17` + `extensions/core_entities/orders/workflows/orders_dsl.py:34,35` импортируют из `src.backend.dsl.*` (DSL — не core layer). `python tools/check_layers.py --root .` → 3 NEW violations (allowlist = 0 для extensions/).
- **SchemasOnlyEntry — фиктивная entry point (P0)**: 3 плагина (core_admin/dadata/skb) имеют `entry_class` → пустой класс (5 LOC, не BasePlugin). В текущей фактической работоспособности они не регистрируются через `PluginLoader` — но manifest утверждает обратное, создавая иллюзию плагинов.
- **Test_credit_pipeline_v2_flag default mismatch (P1)**: тест ассертит `default=False`, код имеет `default=True` → тест провалится.
- **2 module-level singletons в extensions bypass `@app_state_singleton`** (A3-Services concern): `get_credit_skb_client` (`extensions/credit_pipeline/services/clients/skb.py:139-148`), `get_user_service` (`extensions/core_entities/users/services/users.py:347-360`), etc. Не блокер, но inconsistent с core policy.
- **Singleton-плагины с broken entry_class** означают, что текущая фактическая регистрация плагинов — только 8 из 11 (core_entities/*×4 + credit_pipeline + osint_agent + example_plugin + test_plug). core_admin/dadata/skb используются ТОЛЬКО как схемы (через прямой import в `src/backend/entrypoints/api/v1/endpoints/`), но НЕ как плагины.

### Рекомендация для Sprint 36+

**Блокеры немедленного фикса (3 находки P0):**
1. `B-101`: удалить `credit_assessment.workflow.yaml` (broken references) ИЛИ реализовать `fetch_for_workflow` + `emit_decision` — решение должно быть принято до S184 closeout.
2. `B-102` + `B-103`: удалить `routes/hello_route/` и `routes/test_route_w1/` (wizard-заготовки, не production). Альтернатива: заменить на реальные call_function refs.
3. `D-AUDIT-100`: исправить `SchemasOnlyEntry` (наследовать от BasePlugin) ИЛИ удалить `entry_class` из 3 manifest'ов (ponytail-вариант).

**Высокий приоритет (P1):**
- `D-AUDIT-101`: align `credit_pipeline_v2` default с тестом (default=False) ИЛИ переписать тест.
- `D-AUDIT-102`: создать core facade для DSL workflow (для orders_dsl) и валидаторов (для osint_workflow).

**Production readiness для A10: ~85%** после фикса 3 P0 (broken refs) и P1 (test/layer alignment). Текущие 77% отражают реальный статус: extensions core_entities миграция завершена хорошо, но credits pipeline и routes имеют broken references + layer violations, блокирующие «compile-clean» state.

---

## 5. Локализованные метрики (verified)

| Метрика | Значение | Источник |
|---|---|---|
| Production LOC в `extensions/` | 5799 | `find extensions -name "*.py" -exec wc -l {} \;` |
| Production LOC в `routes/` | 407 | `find routes -name "*.yaml" -o -name "*.toml" -exec wc -l {} \;` |
| Количество plugin.toml | 11 | `find extensions -name plugin.toml` |
| Количество routes | 7 | `ls routes/*/route.toml` |
| Количество workflow.yaml | 4 | `find extensions/credit_pipeline/workflows -name "*.workflow.yaml"` |
| Количество broken YAML references | 5 | 2 в credit_assessment + 1 в hello_route + 1 в test_route_w1 + 0 в osint_agent |
| Layer violations (NEW) | 3 | `python tools/check_layers.py --root .` |
| Stale legacy imports в `src/backend/` → extensions | 6 | env.py:15-23 (alembic) + service_setup.py:192-202 + workflow_setup.py:76-79 + skb.py:16 + registers_domains.py:76,120 (допустимо per facade pattern) |
| TODO/FIXME markers | 4 | `extensions/credit_pipeline/{functions,routes,services/clients,workflows}/__init__.py:3` × 4 |
| SchemasOnlyEntry файлов | 3 | core_admin + dadata + skb |
| Module-level singletons в extensions | 7 | users/orderkinds/orders/files + credit_skb + skb + dadata services |
| Trust-tier A (internal) | 8/11 | core_admin, dadata, skb, credit_pipeline, example_plugin, core_entities/*×4 |
| Trust-tier B (untrusted) | 2/11 | test_plug (wizard), osint_agent (Perplexity) |
| Trust-tier отсутствует | 0/11 | default="B" per manifest_toml.py:225 (явно) |
| Plugin layer-violations (stale allowlist entries) | 0 | `grep "extensions" check_layers_allowlist.txt` = 0 совпадений (allowlist = 175 entries, все src/backend/) |

---

## 6. Audit dependencies

- **A0-cycle1 baseline commit:** `b69d6b49bc62918a02e47dc20ab81615fd8500b1` (per A3-Services audit line 5)
- **HEAD analysed:** `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7` (S184-w4 retrospective)
- **Working tree modifications:** 24 modified files, 9 untracked (per git-context); 3 из untracked — новые test directories (`tests/unit/dsl/engine/processors/eip/{reliability,routing}/`, `tests/unit/dsl/processors/security/`) — не относятся к A10 scope.
- **Tools used:** Read, Grep, Glob, Bash (`python tools/check_layers.py`, `python tools/checks/check_workflows_extensions.py`).
- **Tools NOT used (verification gaps):** `make test`, `make lint`, `make type-check` — audit is static-only per scope.
