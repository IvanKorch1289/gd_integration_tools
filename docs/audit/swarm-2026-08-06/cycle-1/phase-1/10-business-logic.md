# Domain Audit — Бизнес-логика (extensions/**)

> Phase 1 / Cycle 1 / Swarm audit (2026-08-06)
> Analyst: independent reviewer (Business Logic domain)
> Scope: `extensions/**` + tests внутри `extensions/**`
> Baseline: `b69d6b49bc62918a02e47dc20ab81615fd8500b1`
> Rules (from AGENTS.md / system prompt, condensed): Python 3.14+, async-first, русские docstrings/comments, бизнес-логика только в `extensions/`, EIP/Camel-like DSL, fail-closed security, layered architecture.

---

## 1. Scope и «не проверено»

### 1.1 In-scope (проверено прочтением/grep/static AST)

* 11 plugin.toml: `core_admin`, `core_entities/{files,orderkinds,orders,users}`, `credit_pipeline`, `dadata`, `example_plugin`, `osint_agent`, `skb`, `test_plug`.
* 117 `.py` файлов, 5 768 LOC, 20 test-файлов в extensions/.
* 4 YAML workflow: `extensions/credit_pipeline/workflows/*.workflow.yaml`.
* Все доменные модули каждого extension: `plugin.py`, `admin.py`, `domain/`, `services/`, `repositories/`, `schemas/`, `workflows/`, `functions/`, `tests/`.
* DI registry, который extensions используют косвенно: `src/backend/core/di/module_registry.py`, `src/backend/core/di/providers/db.py`, `src/backend/core/di/module_registry_extensions.py`.
* Потребители extensions в `src/`: `src/backend/plugins/composition/{workflow,service}_setup.py`, `src/backend/utilities/admin_panel/setup_admin.py`, `src/backend/infrastructure/database/migrations/env.py`, `src/backend/dsl/commands/setup/registers_domains.py` (только import-graph).

### 1.2 Не проверено

* Runtime-флоу под нагрузкой и в Temporal runtime — статический аудит.
* Качество prompts в `extensions/osint_agent/functions/osint_workflow.py::OSINT_REPORT_TEMPLATE` — нет golden-test для LLM-output.
* Точные правила `BasePlugin.on_register_repositories/processors` — проверял поверхностно (deferred у `credit_pipeline`).
* Multi-tenant `CapabilityGate.check_tenant` — упоминается в `example_plugin/plugin.toml` как «Slice 1» (только имя), runtime-test отсутствует в extensions/.
* Код `src/backend/services/integrations/skb.py` (читал только шапку).
* Тесты в `extensions/credit_pipeline/tests/test_actions_registration.py` и др. **не запускал** (среда без `email-validator`; см. §10). Проверял AST/grep.
* `extensions/skb/services/waf_route.py` — прочитан полностью (32 LOC, pure function), дальнейшее не нужно.
* `extensions/credit_pipeline/services/clients/__init__.py` — прочитан, empty `__all__`.

---

## 2. Verified strengths

| # | Что подтверждено | Evidence |
|---|---|---|
| S1 | **Capability gates объявлены в plugin.toml** для всех реальных extensions (net.outbound на конкретные домены, db.read/write на конкретные ресурсы, mq.publish с glob). | `extensions/credit_pipeline/plugin.toml:25-37`, `extensions/core_entities/{files,orderkinds,orders,users}/plugin.toml`, `extensions/osint_agent/plugin.toml:13-17`. |
| S2 | **Никаких прямых `from src.backend.infrastructure`/`from src.backend.services` в extensions/**. Все импорты extension-кода из `src.backend.{core,dsl,schemas,utilities}` + `extensions.<peer>`. | `grep -E "^(from|import) (gd_integration_tools\.infrastructure\|src\.backend\.infrastructure\|infrastructure\.)" extensions/` → 0 hits. `grep "^(from\|import) (gd_integration_tools\.services\|src\.backend\.services\|services\.)"` → 0 hits. |
| S3 | **Domain-модели используют `TenantMixin`** (multi-tenant isolation на уровне SQLAlchemy) для 4/4 core_entities. | `extensions/core_entities/orders/domain/models.py:17`, `users/.../models.py:32`, `files/.../models.py:15`, `orderkinds/.../models.py:19`. |
| S4 | **`test_repository_pattern.py` проверяет facade-boundary** (`infrastructure.repositories.base` не должно встречаться в исходнике репозитория). | `extensions/core_entities/{files,orderkinds,orders}/tests/test_repository_pattern.py`. |
| S5 | **Real business logic в `extensions/credit_pipeline/agents/__init__.py`** — три полноценных async-агента (scoring, parser, decision), не stubs (`stub: False`), с `model_version` маркером. | `extensions/credit_pipeline/agents/__init__.py:53-191` (191 LOC, реальные DTI-вычисления и нормализация). |
| S6 | **`extensions/osint_agent/functions/osint_workflow.py`** реализует полный pipeline: валидация ИНН через `core.dsl.helpers.banking.validate_inn` (через core facade), 3 типа поисковых запросов, парсер отчёта. | `extensions/osint_agent/functions/osint_workflow.py:1-340` (340 LOC). |
| S7 | **Workflow DSL usage** в `extensions/core_entities/orders/workflows/orders_dsl.py` (saga, sensor, sleep, sub_workflow). Корректно использует `WorkflowBuilder` из `src/backend/dsl/workflow/builder/__init__.py`. | `extensions/core_entities/orders/workflows/orders_dsl.py:169-343` (370 LOC). |
| S8 | **User/Order/OrderKind services корректно наследуют `BaseService`** из core. | `extensions/core_entities/users/services/users.py:47-49`, `extensions/core_entities/orders/services/orders.py:47-51`. |
| S9 | **Argon2id password hashing** в `User` (замена устаревшего passlib), OWASP-параметры в `_get_password_hasher()`. | `extensions/core_entities/users/domain/models.py:26-50`. |
| S10 | **Пароли LDAP auto-provisioning** через `AdDirectoryClient` с get-or-create + sync attrs. | `extensions/core_entities/users/services/users.py:176-313` (138 LOC реальной логики). |
| S11 | **Backward-compat shim с `DeprecationWarning`** в `src/backend/services/io/files.py` (legacy → extension) — соответствует R-V15-16 миграции. | `src/backend/services/io/files.py:14-19`. |
| S12 | **Schemas-only extensions** (`core_admin`, `dadata`, `skb`) — минимальный `SchemasOnlyEntry` без логики, чисто Pydantic. Соответствует `S168 W17 P2-10`. | `extensions/core_admin/schemas_only.py`, `extensions/dadata/schemas_only.py`, `extensions/skb/schemas_only.py` (все по 5 LOC). |
| S13 | **`OrderKindRepository` корректно изолирован** в `extensions/core_entities/orderkinds/repositories/orderkinds.py:11` через `core.repositories.base`. | Verified AST. |
| S14 | **Тесты покрывают plugin lifecycle** (BasePlugin subclass, on_load/on_shutdown) для всех core_entities plugins. | `extensions/core_entities/{files,orderkinds,orders,users}/tests/test_plugin_*.py`. |

---

## 3. Findings table

| ID | Priority | path:line | Summary |
|---|---|---|---|
| DOMAIN-P0-001 | **P0** | `src/backend/core/di/module_registry.py:136-137` + `src/backend/core/di/providers/db.py:53-58` | `repos.files` и `repos.orders` маппятся на несуществующие `src.backend.infrastructure.repositories.{files,orders}`. `get_file_repo_provider()` и `repos.orders` → `ModuleNotFoundError` в runtime. **Ломает composition root** (`service_setup.register_all_services`). |
| DOMAIN-P0-002 | **P0** | `src/backend/plugins/composition/workflow_setup.py:76-83` | Импортирует `extensions.core_entities.orders.workflows.orders_saga.build_orders_saga_workflow` и `extensions.credit_pipeline.workflows.payments_saga.build_payments_saga_workflow` — **оба модуля не существуют**. При `WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=true` → `ModuleNotFoundError`. |
| DOMAIN-P0-003 | **P0** | `extensions/credit_pipeline/agents/__init__.py:84-94` (`scoring_agent`) | **Fail-OPEN в кредитном скоринге**: если нет `income`/`amount` → `base_score = 750` (LOW risk). В реальном кредитном конвейере это означает выдачу кредита неизвестному клиенту. Маркер `stub: False` маскирует это как production-ready. |
| DOMAIN-P0-004 | **P0** | `extensions/osint_agent/functions/osint_workflow.py:309-313, 333-334` | **Fail-OPEN в OSINT-агенте**: при исключении в `_search_multi_provider` результаты молча обнуляются; при сбое LLM-gateway `raw_text = prompt` (т.е. template возвращается как «отчёт»). Отчёт проходит валидацию (`validate_report`) без реальных данных. |
| DOMAIN-P1-001 | **P1** | `extensions/core_entities/orders/services/orders.py:44, 413` | **Прямой импорт infrastructure layer** через `importlib.import_module("src.backend.infrastructure.external_apis.s3")`. Dynamic-import обходит AST-линтер. Нарушает инвариант `extensions → only core + capability-checked facades`. |
| DOMAIN-P1-002 | **P1** | `extensions/core_entities/orders/services/orders.py:22`, `extensions/core_entities/orderkinds/services/orderkinds.py:15` | **Soft layer violation**: импорт из `src.backend.core.integrations.skb` — это re-export shim `src.backend.services.integrations.skb`. Документировано (ADR-0207), но формально это мост из extensions в services через core. |
| DOMAIN-P1-003 | **P1** | `extensions/core_entities/orders/workflows/orders_dsl.py:370 LOC` | `build_all_order_workflows()` определён, **не вызывается ни одним продьюсером в `src/`** (production использует отсутствующий `orders_saga` из P0-002). Extension не регистрирует workflow через lifecycle-hook `on_register_workflows` — модуль изолирован от runtime. |
| DOMAIN-P1-004 | **P1** | `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml:22, 30, 43` | YAML workflow ссылается на несуществующие функции: `extensions.credit_pipeline.services.clients.skb:fetch_for_workflow` (нет в skb.py: только `get_request_kinds/create_request/get_result`), `extensions.credit_pipeline.functions.publish:emit_decision` (модуль `publish.py` отсутствует целиком). Workflow-loader сломается при попытке резолва. |
| DOMAIN-P2-001 | **P2** | `extensions/credit_pipeline/functions/__init__.py:3`, `routes/__init__.py:3`, `services/clients/__init__.py:3`, `workflows/__init__.py:3` | TODO-комментарии в scaffold-docstring, упоминающие Sprint 8+ Team T3 как план. Устаревший signal — большая часть из TODO выполнена (agent'ы реализованы, normalize.py создан, SKB client написан), но TODO не удалены. |
| DOMAIN-P2-002 | **P2** | `extensions/core_entities/files/repositories/files.py` (76 LOC), `extensions/core_entities/orders/repositories/orders.py` (108 LOC) | Репозитории в extensions существуют, **но не используются**: services идут через `importlib.import_module("extensions.<peer>.repositories.<name>")` для orders, но через **сломанный** `get_file_repo_provider()` для files. После фикса P0-001 они могут стать dead code (если останется indirect через DI). |
| DOMAIN-P2-003 | **P2** | `extensions/credit_pipeline/services/clients/skb.py:79-149` | `CreditSKBClient` реализован, но **используется только в собственных smoke-тестах** (`test_skb_client_smoke.py`); в production нет ни одного caller (verified grep). За feature_flag (default OFF) — намеренный scaffold, но не задокументировано как таковой. |
| DOMAIN-P2-004 | **P2** | `extensions/credit_pipeline/plugin.toml:6-19` (header comment) | TODO-список в самом manifest (SKB client, NBKI/CBR/Spark, normalize, workflow, routes, models, actions). **Многие пункты выполнены** (SKB client, normalize, models, actions 3 шт.), но TODO остался. Вводит в заблуждение читателя manifest. |
| DOMAIN-P2-005 | **P2** | `extensions/credit_pipeline/tests/test_workflow_yaml.py` | Smoke-test `credit_assessment.workflow.yaml` **не проверяет, что `function:` ссылки резолвятся** — тест проходит, хотя `fetch_for_workflow`/`emit_decision` не существуют (см. P1-004). |
| DOMAIN-P3-001 | **P3** | `extensions/credit_pipeline/plugin.py:44-58` + `extensions/osint_agent/plugin.py:48-55` | **Дублирование `_make_handler`** (action wrapper, извлекает payload из kwargs). 2 копии по ~10 LOC идентичной логики. |
| DOMAIN-P3-002 | **P3** | `extensions/core_entities/orders/services/orders.py:18`, `extensions/core_entities/users/services/users.py:...` (broad except pattern) | `except Exception` встречается 15+ раз. Часть — legitimate boundary wrapping (ServiceError). Часть в `_index_order_async` (fire-and-forget, помечено `# noqa: BLE001`) — спорно, но документировано. Не блокер. |
| DOMAIN-P4-001 | **P4** | `extensions/example_plugin/plugin.toml:32-79` | Документированный V15 GAP Slice 1: только имена capabilities в `[[tenants]]`, без scope. Не реализован `[[tenants]]` блок в реальных multi-tenant extensions (`credit_pipeline`, `osint_agent`). |
| DOMAIN-P4-002 | **P4** | `extensions/credit_pipeline/workflows/*.workflow.yaml` (4 файла, 254 LOC суммарно) | `code_interpreter_loop`, `multi_agent_supervisor`, `rag_augmented_saga` ссылаются на `services.ai.*` функции, которые **не существуют в extensions** (README явно говорит «декларативный пример, функции — отдельный wave»). Не блокер, но **не работают** как real workflows. |

---

## 4. Detailed evidence

### DOMAIN-P0-001 — DI registry dead-link

**path**: `src/backend/core/di/module_registry.py:136-137`
```python
"repos.files": f"{_INFRA}.repositories.files",       # module does not exist
"repos.orders": f"{_INFRA}.repositories.orders",     # module does not exist
```

`repos.users`, `repos.express_*`, `repos.connector_configs` тоже missing, но в extensions используются только `files` и `orders`.

**Caller** (`src/backend/core/di/providers/db.py:53-58`):
```python
def get_file_repo_provider() -> Any:
    if "file_repo" in _overrides:
        return _overrides["file_repo"]
    module = resolve_module("repos.files")          # → ImportError
    return module.get_file_repo()
```

**Trigger** (`src/backend/plugins/composition/service_setup.py:204-207`):
```python
register_factory("orders", get_order_service)        # uses extensions.core_entities.orders.services.orders
register_factory("files", get_file_service)          # calls get_file_repo_provider() → ModuleNotFoundError
register_factory("orderkinds", get_order_kind_service)
```

**Verified runtime**:
```
$ python -c "from src.backend.core.di.providers.db import get_file_repo_provider; get_file_repo_provider()"
ModuleNotFoundError: No module named 'src.backend.infrastructure.repositories.files'

$ python -c "from src.backend.core.di.module_registry import validate_modules; ..." | grep files
  repos.files                              -> src.backend.infrastructure.repositories.files
  repos.orders                             -> src.backend.infrastructure.repositories.orders
```

**Impact**: P0 — **composition root падает на старте приложения**. `register_all_services()` в `service_setup.py` импортирует `extensions.core_entities.files.services.files.get_file_service`, который при первом вызове вызывает `get_file_repo_provider()` → `ModuleNotFoundError`. Это блокирует старт backend.

**Recommendation** (минимальная):
1. Удалить `repos.files`/`repos.orders` из `INFRA_MODULES` в `src/backend/core/di/module_registry.py`.
2. В `extensions/core_entities/files/services/files.py::get_file_service()` перейти на прямой `from extensions.core_entities.files.repositories.files import get_file_repo` (вместо сломанного `get_file_repo_provider()`).
3. Аналогично для orders — service уже использует `importlib.import_module("extensions.core_entities.orders.repositories.orders")` (см. `extensions/core_entities/orders/services/orders.py:411`); можно просто убрать динамику.
4. Расширения должны регистрировать свои модули через `register_extension_module()` (см. `src/backend/core/di/module_registry_extensions.py`), чтобы не зависеть от core INFRA_MODULES.

**Test criterion**: `pytest -k "test_get_file_repo_provider_returns_extension_repo"` — `get_file_repo_provider()` (после фикса) должен вернуть экземпляр `extensions.core_entities.files.repositories.files.FileRepository`. Также `python -c "from src.backend.plugins.composition.service_setup import register_all_services; register_all_services()"` без падения.

---

### DOMAIN-P0-002 — Saga import dead-link

**path**: `src/backend/plugins/composition/workflow_setup.py:76-83`
```python
from extensions.core_entities.orders.workflows.orders_saga import (
    build_orders_saga_workflow,
)
from extensions.credit_pipeline.workflows.payments_saga import (
    build_payments_saga_workflow,
)
```

**Verified**:
```
$ find extensions -name "orders_saga*" -o -name "payments_saga*"
# пусто
```

**Что есть**:
* `extensions/core_entities/orders/workflows/orders_dsl.py` (370 LOC) — другой модуль, не `orders_saga`.
* `extensions/credit_pipeline/workflows/{credit_assessment,code_interpreter_loop,multi_agent_supervisor,rag_augmented_saga}.workflow.yaml` — четыре YAML-файла, никакого `payments_saga.py`.

**Impact**: P0 — при `settings.workflow.bootstrap_defaults_enabled=True` (флаг существует в `src/backend/core/config/settings.py` — не проверял deep, но `workflow_setup.py` ссылается на `settings.workflow.bootstrap_defaults_enabled`) `_bootstrap_default_declarations()` упадёт на `ImportError`.

**Recommendation**:
* Либо восстановить `extensions.core_entities.orders.workflows.orders_saga` с `build_orders_saga_workflow()` (Pydantic WorkflowDeclaration).
* Либо удалить импорт из `workflow_setup.py`, заменив на `from extensions.core_entities.orders.workflows.orders_dsl import build_all_order_workflows` (этот существует и возвращает dict).

**Test criterion**: `pytest -k test_bootstrap_default_declarations` — должен пройти без `ImportError` при любом значении флага.

---

### DOMAIN-P0-003 — Fail-OPEN кредитный скоринг

**path**: `extensions/credit_pipeline/agents/__init__.py:84-94`
```python
base_score = 750  # Default for unknown
if income > 0 and amount > 0:
    if dti < 0.3:
        base_score = 800
    elif dti < 0.5:
        base_score = 720
    elif dti < 0.7:
        base_score = 650
    else:
        base_score = 500
```

`scoring_agent` отдаёт `risk_class="LOW"` при `score >= 700` (`apply_rules` в `extensions/credit_pipeline/functions/normalize.py:41`). `decision_agent` одобряет при `credit_score >= 600` (`extensions/credit_pipeline/agents/__init__.py:39, 170`). **Пустой/неполный payload → score 750 → APPROVE**.

`stub: False` маркер на строке 106 явно говорит «это НЕ stub». Но фактически это rule-based placeholder (`s76-w1-rule-based-v1` model_version).

**Impact**: P0 — **fail-open в финансовом домене**. Плагин зарегистрирован как `trust_tier = "A"` (banking-critical, `extensions/credit_pipeline/plugin.toml:22`), capabilities для `*.skb-techno.ru` и `*.nbki.ru` уже декларированы. Если этот код достигнет production до замены на ML/SKB/НБКИ integration — silent credit approval для неизвестных клиентов.

**Recommendation**:
1. Сделать `base_score` явным `0` (REJECT) при отсутствии обязательных полей, **или** поднять исключение `ValueError("insufficient data for scoring")` чтобы DSL-step упал (fail-closed по умолчанию).
2. Удалить маркер `stub: False` или установить `stub: True` пока это rule-based placeholder.
3. Переименовать `model_version` в `s76-w1-rule-based-PLACEHOLDER` для однозначности.

**Test criterion**:
```python
async def test_scoring_agent_missing_data_raises_or_rejects():
    result = await scoring_agent({})  # empty payload
    assert result["credit_score"] < 600 or "raised"  # не должен одобрять
```

---

### DOMAIN-P0-004 — Fail-OPEN OSINT-агент

**path 1**: `extensions/osint_agent/functions/osint_workflow.py:309-313`
```python
try:
    results_general = await _search_multi_provider(queries["general"])
    ...
except Exception:
    results_general = {"perplexity": None, "tavily": None, "scraped": []}
    ...
```

Если все три поиска упали → отчёт формируется на пустых данных.

**path 2**: `extensions/osint_agent/functions/osint_workflow.py:323-334`
```python
try:
    from src.backend.core.ai.llm_gateway import get_litellm_gateway
    gateway = get_litellm_gateway()
    response = await gateway.acompletion(...)
    raw_text = response.get(...).get(...).get("content", "")
except Exception:
    raw_text = prompt   # !!! LLM-sbой → template уходит как «отчёт»
```

`prompt` сам по себе валиден по `MAX_REPORT_LENGTH=3000` (`osint_workflow.py:67`) и `validate_report(raw_text)` парсит секции. **Если LLM упал, отчёт содержит только шаблон — проходит валидацию как будто всё OK.**

**Impact**: P0 — для OSINT-агента, который используется как due-diligence по клиенту, fail-OPEN означает «выдать пустой/неверный отчёт, когда внешний API/ML упал». Это может привести к принятию бизнес-решений на невалидных данных.

**Recommendation**:
1. Если `_search_multi_provider` упал для всех трёх запросов → поднять исключение (`RuntimeError("OSINT: search providers unavailable")`); пусть DSL-step решает retry/fallback policy.
2. Если LLM-gateway упал → поднять исключение вместо `raw_text = prompt`.
3. Добавить `validate_inn` check для ИНН и явный контракт: `if not results: raise ValueError("no search results")`.

**Test criterion**:
```python
async def test_run_osint_when_search_fails_raises():
    with mock.patch(..., side_effect=ConnectionError):
        with pytest.raises(RuntimeError):
            await run_osint({"inn": "7707083893"})
```

---

### DOMAIN-P1-001 — Прямой import infrastructure через importlib

**path**: `extensions/core_entities/orders/services/orders.py:44, 413`
```python
_S3_MOD = "src.backend.infrastructure.external_apis.s3"  # line 44
...
s3_service = importlib.import_module(_S3_MOD).get_s3_service_dependency()  # line 413
```

Dynamic import через `importlib.import_module` обходит AST-линтер слоёв (по комментарию в `src/backend/core/di/module_registry.py:72-75`). **Это нарушение архитектурного инварианта** `extensions → only core + capability-checked facades`, хоть и технически выполнимо.

**Impact**: P1 — слой нарушен; extensions напрямую зависит от infrastructure. Если `src/backend/infrastructure/external_apis/s3.py` рефакторится — ломается `OrderService` без compile-time-warning.

**Recommendation**:
* Ввести core-facade (по образцу `core.integrations.web_search`): `src/backend/core/integrations/s3.py` с `get_s3_service_dependency()` через `resolve_module("external_apis.s3")` (как в DI-providers).
* Extension должен импортировать только из `src.backend.core.integrations.s3`.

**Test criterion**: `extensions/core_entities/orders/tests/test_layer_boundary.py::test_no_direct_infra_import` — AST-check по `extensions/core_entities/orders/services/orders.py` не должен содержать literal `"src.backend.infrastructure"` (по аналогии с `test_repository_pattern.py:30-39`).

---

### DOMAIN-P1-002 — Soft layer violation через core shim

**path**: `extensions/core_entities/orders/services/orders.py:22`, `extensions/core_entities/orderkinds/services/orderkinds.py:15`
```python
from src.backend.core.integrations.skb import APISKBService, get_skb_service
```

`src/backend/core/integrations/skb.py` — это re-export shim (`from src.backend.services.integrations.skb import APISKBService, get_skb_service`). Документировано в ADR-0207. Формально extensions → services через core-shim.

**Impact**: P1 — soft violation. Архитектурно правильный путь — `src/backend/core/integrations/skb.py` должен быть **facade** (как `core.integrations.web_search.py`), а не shim. Сейчас он re-export-ит класс напрямую, теряя indirection.

**Recommendation**:
* `src/backend/core/integrations/skb.py` переписать как facade (как `web_search.py`): класс резолвится через `infrastructure_locator.get_skb_service_class()`.
* Extensions импортируют `from src.backend.core.integrations.skb import APISKBService, get_skb_service` — сигнатура не меняется.

**Test criterion**: `pytest -k test_core_integrations_skb_is_facade` — `inspect.getsource(skb_shim)` не содержит `from src.backend.services`.

---

### DOMAIN-P1-003 — `orders_dsl.py` disconnected from runtime

**path**: `extensions/core_entities/orders/workflows/orders_dsl.py` (370 LOC)

Модуль определяет 5 `*_workflow_spec()` функций + `build_all_order_workflows()`. **Ни один production caller в `src/`** (verified grep):
```
$ grep -rn "orders_dsl\|build_all_order_workflows" src/
# пусто
```

Production код импортирует несуществующий `extensions.core_entities.orders.workflows.orders_saga` (см. P0-002). То есть:
* `orders_dsl.py` — полноценная реализация (saga, sensor, retry, sub_workflow), но **изолирована**.
* `orders_saga.py` — то, что ждёт `workflow_setup.py`, **отсутствует**.

**Impact**: P1 — 370 LOC бизнес-логики не доходят до runtime. Workflows из `orders_dsl.py` (5 штук) не зарегистрированы, поэтому orders full-processing pipeline работает через legacy путь, минуя Temporal durable semantics.

**Recommendation**:
* Переименовать `orders_dsl.py` → `orders_saga.py` (соответствует ожиданию `workflow_setup.py`).
* Или обновить `workflow_setup.py:76-83` чтобы импортировать `build_all_order_workflows()` из текущего `orders_dsl.py`.
* Добавить `extensions/core_entities/orders/plugin.py::on_register_workflows()` hook чтобы регистрация шла через plugin lifecycle, а не composition root.

**Test criterion**:
```python
# extensions/core_entities/orders/tests/test_workflow_dsl.py
def test_build_all_order_workflows_returns_five():
    flows = build_all_order_workflows()
    assert set(flows) == {"notifications.send_email", "orders.create_skb",
                          "orders.poll_skb_result", "orders.send_skb_result",
                          "orders.full_processing"}
```

(Тестов для `orders_dsl.py` сейчас **нет в extensions** — отдельный sub-issue, см. P2-area.)

---

### DOMAIN-P1-004 — Workflow YAML dead references

**path**: `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml:22, 30, 43`
```yaml
activities:
  - name: fetch_skb_report
    function: extensions.credit_pipeline.services.clients.skb:fetch_for_workflow    # не существует
  - name: fetch_nbki_report
    function: extensions.credit_pipeline.services.clients.skb:fetch_for_workflow    # не существует
  - name: normalize_responses
    function: extensions.credit_pipeline.functions.normalize:apply_rules           # OK
  - name: publish_decision
    function: extensions.credit_pipeline.functions.publish:emit_decision            # модуль publish.py не существует
```

**Verified**:
```
$ grep "def " extensions/credit_pipeline/services/clients/skb.py
def __init__, _request, _waf_route, get_request_kinds, create_request, get_result, get_credit_skb_client
# fetch_for_workflow — отсутствует

$ find extensions/credit_pipeline/functions -name "publish.py"
# пусто
```

**Impact**: P1 — при runtime-регистрации workflow через `WorkflowCompilerRegistry.bulk_register()` и попытке резолва activity функций — `ImportError` для `fetch_for_workflow` и `emit_decision`.

**Recommendation**:
1. Добавить `async def fetch_for_workflow(payload: dict) -> dict` в `skb.py` (тривиальный wrapper над существующими `get_request_kinds/create_request/get_result`).
2. Создать `extensions/credit_pipeline/functions/publish.py` с `async def emit_decision(payload: dict) -> dict` (минимум — `logger.info("decision=%s", payload)`; реальная публикация — Sprint 8+).
3. **Или** упростить workflow до одного `apply_rules` step'а пока нет SKB/НБКИ clients.

**Test criterion**:
```python
# extensions/credit_pipeline/tests/test_workflow_yaml.py (расширить)
def test_workflow_yaml_activity_functions_resolve():
    for activity in yaml.safe_load(_WORKFLOW_PATH.read_text())["activities"]:
        mod_path, fn_name = activity["function"].split(":")
        mod = importlib.import_module(mod_path)
        assert hasattr(mod, fn_name), f"missing {activity['function']}"
```

---

### DOMAIN-P2-001 — Устаревшие TODO в docstrings

**path**: `extensions/credit_pipeline/{functions,routes,services/clients,workflows}/__init__.py:3`

Все 4 файла содержат TODO-список «Sprint 8+ Team T3: реализовать X/Y/Z». Большая часть выполнена (SKB client, normalize.py, domain/models.py, actions `credit_pipeline.{score,parse,decide}`), но TODO не удалены.

**Impact**: P2 — мислид для читателя. Создаёт впечатление незавершённого scaffold, когда фактически scaffold уже далеко за пределами TODO.

**Recommendation**: убрать TODO-списки или заменить на «Status: implemented per S76 W2» с коротким changelog.

---

### DOMAIN-P2-002 — Repositories в extensions не используются

**path**: `extensions/core_entities/files/repositories/files.py:64-75`, `extensions/core_entities/orders/repositories/orders.py:98-107`

`get_file_repo()` и `get_order_repo()` определены в extensions, **но `get_file_service()` идёт через `get_file_repo_provider()`** (сломанный P0-001), а `get_order_service()` использует `importlib.import_module("extensions.core_entities.orders.repositories.orders")` — dynamic import.

**Impact**: P2 — после фикса P0-001 нужно решить: extension-repo canonical (рекомендуется) или продолжать indirection. Текущий mix — architectural smell.

**Recommendation**: extension-repo становится canonical для своих services, инжектится напрямую (без `importlib`). См. P1-001.

---

### DOMAIN-P2-003 — SKB client без production caller

**path**: `extensions/credit_pipeline/services/clients/skb.py:149 LOC`

Verified: `grep -rn "CreditSKBClient\|get_credit_skb_client" extensions/ src/backend/core/` — все ссылки либо внутри `skb.py`, либо в `test_skb_client_smoke.py`. **В production нет ни одного caller.**

**Impact**: P2 — scaffold (под `feature_flag.credit_pipeline_v2`, default OFF), но не отмечен как таковой явно. 149 LOC мёртвого кода в проде.

**Recommendation**: либо задокументировать явно `# Scaffold: gated by feature_flag.credit_pipeline_v2`, либо переключить feature flag default ON и подключить к реальному callsite.

---

### DOMAIN-P2-004 — TODO в manifest header

**path**: `extensions/credit_pipeline/plugin.toml:6-19`

Manifest содержит inline TODO-список в комментарии header. Непосредственно перед `[plugin]`. 7 пунктов, многие выполнены.

**Impact**: P2 — manifest-header — публичный документ для PluginLoader; TODO там — сигнал «плагин scaffold».

**Recommendation**: убрать TODO или заменить на status note.

---

### DOMAIN-P2-005 — Workflow YAML test не проверяет резолв функций

**path**: `extensions/credit_pipeline/tests/test_workflow_yaml.py:23-48`

Тест проверяет: имя, версию, наличие `activities`/`steps`/`compensation`, `rule_engine`. **Не проверяет**, что `function:` references резолвятся в importable модули.

**Impact**: P2 — тест зелёный при сломанном workflow (см. P1-004).

**Recommendation**: добавить `test_workflow_yaml_activity_functions_resolve` (см. P1-004).

---

### DOMAIN-P3-001 — Дублирование `_make_handler`

**path**: `extensions/credit_pipeline/plugin.py:44-58`, `extensions/osint_agent/plugin.py:48-55`

Оба файла содержат копию `_make_handler(agent)` (~10 LOC):
```python
def _make_handler(agent):
    async def _handler(**kwargs):
        payload = kwargs.get("payload")
        if payload is None:
            payload = {}
        return await agent(payload)
    return _handler
```

**Recommendation**: вынести в `src/backend/core/interfaces/plugin.py` (или новый `src/backend/core/dsl/helpers.py`) как `make_action_payload_wrapper(agent)`. Extensions импортируют из core.

**LOC delta**: −20 в extensions, +5 в core = net −15.

**Test criterion**: после рефакторинга оба существующих теста (`test_actions_registration.py`, `test_osint_workflow.py`) остаются зелёными.

---

### DOMAIN-P4-001 — V15 GAP Slice 1

**path**: `extensions/example_plugin/plugin.toml:32-79` (комментарий-документация)

Документирует что `[[tenants]]` с `capabilities = [...]` (только имена, без scope) ещё не реализован. **Ни один extension не использует этот паттерн** в реальности (verified grep по всем plugin.toml: ни одного `[[tenants]]` блока).

**Recommendation**: реализовать `[[tenants]]` parsing в `load_plugin_manifest` (S172+, post backlog) для extensions с `tenant_aware = true`.

---

### DOMAIN-P4-002 — Workflow YAML для AI-примеров без функций

**path**: `extensions/credit_pipeline/workflows/{code_interpreter_loop,multi_agent_supervisor,rag_augmented_saga}.workflow.yaml` (159 LOC суммарно)

Все ссылаются на `services.ai.*` функции (нет в extensions, нет в `src/backend/core/services/` — не проверял deep). README явно говорит:
> «Реализация функций — отдельный wave (вне S12 K4 W1 scope). Workflow YAML — это **декларация**, она не требует физического кода для парсинга и dry-run. При фактическом запуске Temporal вернёт ``UnknownActivity`` для несуществующих handler'ов — для S12 это OK (декларативный пример).»

**Impact**: P4 — примеры, не production workflows. Не блокер, но вводят в заблуждение если кто-то попытается их реально запустить.

**Recommendation**: переместить в `docs/examples/workflows/` или явно пометить `# EXAMPLE ONLY — not wired to runtime`.

---

## 5. Contradictions / overlaps to flag

### C1. Расхождение `orders_dsl` ↔ `orders_saga`
Production ждёт `extensions.core_entities.orders.workflows.orders_saga`, extension содержит `orders_dsl`. **Чей это баг — production или extension — непонятно из комментариев**; нужно согласование с владельцем workflow-bootstrap.

### C2. `get_file_service` через два сломанных пути
* Extension `extensions/core_entities/files/services/files.py:59` использует `get_file_repo_provider()` → broken.
* Shim `src/backend/services/io/files.py:11` re-export-ит extension version → тоже broken.

Оба пути ведут к одному broken `INFRA_MODULES["repos.files"]`. **Чинить нужно в одном месте** (`INFRA_MODULES`), но **дополнительно** — переключить extension на свой repo.

### C3. `test_repository_pattern.py` vs реальная imports
Все 4 файла `test_repository_pattern.py` проверяют, что `infrastructure.repositories.base` НЕ появляется в исходнике extension-репозитория. **Тесты проходят**. Но реальное использование идёт через DI-facade (`get_file_repo_provider()`), а facade указывает на infrastructure → **indirect** violation, который тест не ловит (он проверяет только AST extension-репозитория).

### C4. Capability declaration vs actual usage
* `extensions/credit_pipeline/plugin.toml` декларирует `db.read/db.write credit_applications`, `db.read/db.write credit_reports`. **Ни один extension-repo не использует `credit_applications` или `credit_reports`** (extension-ресурсы: `files`, `orders`, `orderkinds`, `users`). Это **dead capability declarations** — намекает, что Sprint 8+ должен добавить эти ресурсы.
* Аналогично `*.nbki.ru` net.outbound — нет NBKI client (`services/clients/nbki.py` отсутствует).

### C5. `_make_handler` дубликат (см. P3-001) — типичный copy-paste при отсутствии helper в core.

---

## 6. Readiness score 0–100

### 6.1 Формула

```
readiness = 100
  − 25 × (P0 count)        # каждый P0 = −25
  − 10 × (P1 count)        # каждый P1 = −10
  −  3 × (P2 count)        # каждый P2 = −3
  −  1 × (P3 count)        # каждый P3 = −1
  +  (strengths bonus, cap +10)
  clamp [0, 100]
```

### 6.2 Подсчёт

| Bucket | Count | Subtotal |
|---|---|---|
| P0 | 4 | −100 |
| P1 | 4 | −40 |
| P2 | 5 | −15 |
| P3 | 2 | −2 |
| Strengths bonus | 14 strengths verified | +10 |
| **Pre-clamp** | | **−147** |
| **Clamped to [0, 100]** | | **0** |

### 6.3 Обоснование

* **4 P0 findings** в одной extension-ветке (orders/files) и одном core-composition (`workflow_setup.py`). Любой из них **блокирует production startup**:
  * P0-001 — composition root падает на `get_file_service()`.
  * P0-002 — composition root падает при `bootstrap_defaults_enabled=true`.
  * P0-003/P0-004 — fail-open в financial/diligence доменах (security/data-loss risk).
* **По правилу агента** «оценка ≥80 запрещена при наличии P0/P1» — даже если бы формула давала >80, пришлось бы снизить до 80 max. Текущая формула даёт **0** (clamp), что **соответствует реальности**: extension-ветка core_entities/orders+files неработоспособна в runtime.
* Strengths (S1–S14) подтверждены, но они — **локальные** (хорошо написано внутри изолированного файла); они не компенсируют сломанный composition.

### 6.4 Итог

**Readiness = 0/100** — формально. Реально: **~30%** (структура есть, тесты есть, capability gates есть, real logic есть), но **блокирующие P0 в startup-цепочке** означают «не готово к запуску».

---

## 7. Recommended next tasks

### Приоритет 1 (блокеры запуска)

1. **[P0-001] Fix `repos.files`/`repos.orders` DI registry.**
   * Удалить `src/backend/core/di/module_registry.py:136-137` (`repos.files`, `repos.orders`).
   * Заменить `extensions/core_entities/files/services/files.py::get_file_service()` на прямой `from extensions.core_entities.files.repositories.files import get_file_repo`.
   * Прогнать `python -c "from src.backend.plugins.composition.service_setup import register_all_services; register_all_services()"` — должно пройти.

2. **[P0-002] Resolve `orders_saga` / `payments_saga` import.**
   * Переименовать `extensions/core_entities/orders/workflows/orders_dsl.py` → `orders_saga.py`, экспортировать `build_orders_saga_workflow()`.
   * Создать `extensions/credit_pipeline/workflows/payments_saga.py` с `build_payments_saga_workflow()` (минимум — single-activity workflow).
   * Запустить `python -c "from src.backend.plugins.composition.workflow_setup import _bootstrap_default_declarations; ..."` при `WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=true`.

3. **[P0-003] Fail-closed в `scoring_agent`.**
   * Минимальный фикс: `if not income or not amount: raise ValueError("scoring requires income + amount")`.
   * Или вернуть `credit_score = 0, risk_class="HIGH"` + `decision="REJECT"` (без одобрения).

4. **[P0-004] Fail-closed в `run_osint`.**
   * Заменить `except Exception: raw_text = prompt` на `raise`.
   * Заменить `except Exception: results_general = {...}` на `raise` (или логировать warning + вернуть dict с пустым результатом, **помеченным** как `degraded: True`).

### Приоритет 2 (architecture cleanup)

5. **[P1-001] Устранить прямой importlib infrastructure import в `orders.py:44`.**
   * Создать `src/backend/core/integrations/s3.py` facade (по образцу `core.integrations.web_search.py`).
   * Extension использует `from src.backend.core.integrations.s3 import get_s3_service_dependency`.

6. **[P1-003] Подключить `orders_dsl`/`orders_saga` к plugin lifecycle.**
   * Добавить `OrdersPlugin.on_register_workflows()` hook (если есть в BasePlugin; иначе — отдельный registry).
   * Убрать `extensions.core_entities.orders.workflows.orders_saga` из `_bootstrap_default_declarations` (пусть регистрирует plugin).

7. **[P1-004] Добавить `fetch_for_workflow` в `extensions/credit_pipeline/services/clients/skb.py` и создать `extensions/credit_pipeline/functions/publish.py` с `emit_decision`.**

### Приоритет 3 (tests / docs)

8. **[P2-002, P2-005] Добавить test_workflow_dsl.py для orders_dsl и расширить test_workflow_yaml.py для credit_pipeline.**
9. **[P2-001, P2-004] Удалить устаревшие TODO.**
10. **[P3-001] Вынести `_make_handler` в `src/backend/core/interfaces/plugin.py` (или новый helper).**
11. **[P4-001] Реализовать `[[tenants]]` parsing в `load_plugin_manifest`** (для `tenant_aware = true` extensions: `credit_pipeline`, `osint_agent`, `test_plug`).

---

## 8. Commands run

### 8.1 Repo discovery
```bash
$ git log --oneline -1 b69d6b49bc62918a02e47dc20ab81615fd8500b1
b69d6b49 feat(infra): DLQ partition migration script + dry-run tests (B-22, cycle 38, D-AUDIT-#15)

$ git diff --stat HEAD -- src/backend/infrastructure/storage/s3.py
# (no changes from HEAD; working-tree modification is pre-existing per brief)

$ git diff --name-only b69d6b49bc62918a02e47dc20ab81615fd8500b1 HEAD -- extensions/
# (no changes — extensions unchanged since baseline)
```

### 8.2 Static analysis
```bash
$ grep -rE "^(from|import) (gd_integration_tools\.infrastructure|src\.backend\.infrastructure|infrastructure\.)" extensions/
# (no results)

$ grep -rE "^(from|import) (gd_integration_tools\.services|src\.backend\.services|services\.)" extensions/
# (no results)

$ grep -rn "from src.backend" extensions/ --include="*.py" | awk '{print $4}' | sort -u
# (only core, dsl, schemas, utilities)

$ python -c "import ast, os; ... # count literal src.backend.infrastructure strings in extensions"
# → 1 active (orders.py:44)

$ python -c "import ast, os; ... # count src.backend.services strings"
# → 0 active (все в docstrings/comments)

$ grep -rn "TODO\|FIXME\|XXX\|HACK\|NotImplementedError" extensions/ --include="*.py"
# 4 hits, все — TODO в scaffold-docstring

$ grep -rn "^\s*pass$\|^\s*\.\.\.$" extensions/ --include="*.py"
# 3 hits: orders/services/orders.py:38 (TYPE_CHECKING pass), osint_agent/plugin.py:82,86 (no-op hooks)
```

### 8.3 DI registry verification
```bash
$ python -c "from src.backend.core.di.providers.db import get_file_repo_provider; get_file_repo_provider()"
ModuleNotFoundError: No module named 'src.backend.infrastructure.repositories.files'

$ python -c "from src.backend.core.di.module_registry import validate_modules; ..."
# 14 missing modules total
# critical: repos.files, repos.orders (called from extensions)

$ find src/backend/infrastructure/repositories -name "files*" -o -name "orders*"
# (no files — only ai_feedback_mongo, connector_configs_mongo, express_*, notebooks_mongo, outbox, rule_engine_repository)
```

### 8.4 Cross-module consistency
```bash
$ find extensions -name "orders_saga*" -o -name "payments_saga*"
# (empty)

$ grep -rn "from extensions.core_entities.orders.workflows" src/
src/backend/plugins/composition/workflow_setup.py:76
# (imports orders_saga — doesn't exist)

$ find extensions -name "publish.py" -path "*credit_pipeline*"
# (empty — credit_assessment.workflow.yaml references emit_decision in missing module)
```

### 8.5 Import-graph verification
```bash
$ grep -rn "from extensions.core_entities" src/ | head -20
src/backend/infrastructure/database/migrations/env.py: imports 4 domain models
src/backend/utilities/admin_panel/setup_admin.py: imports 4 admin views
src/backend/plugins/composition/service_setup.py: imports 3 services
src/backend/plugins/composition/workflow_setup.py: imports 2 (both missing)
src/backend/dsl/commands/setup/registers_domains.py: imports schemas + service
```

### 8.6 Module-count summary
```bash
$ find extensions -name "*.py" ! -path "*__pycache__*" -exec wc -l {} + | tail -1
5767  итого

$ find extensions -name "*.py" ! -path "*__pycache__*" | wc -l
117

$ find extensions -name "test_*.py" ! -path "*__pycache__*" | wc -l
20

$ find extensions -name "*.toml" -type f | wc -l
11

$ find extensions -name "*.yaml" -type f | wc -l
4
```

### 8.7 Test execution (не удалось — missing dep)
```bash
$ python -m pytest extensions/credit_pipeline/tests/ -x --tb=short -q 2>&1 | tail -3
ERROR extensions/credit_pipeline/tests/test_actions_registration.py
1 error in 0.21s
# ImportError: email-validator is not installed
# (env-only issue; pyproject.toml declares pydantic[email]>=2.10.3 — runtime env incomplete)
```

### 8.8 Static AST walk
```bash
$ python -c "
import ast, os
for root, dirs, files in os.walk('extensions'):
    if '__pycache__' in root: continue
    for f in files:
        if not f.endswith('.py'): continue
        tree = ast.parse(open(os.path.join(root,f)).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if 'src.backend.infrastructure' in node.value and 'удалён' not in node.value:
                    print(f, node.lineno, node.value[:80])
"
# extensions/core_entities/orders/services/orders.py:44: src.backend.infrastructure.external_apis.s3
```

---

## 9. Сводка

* **Real business logic** в extensions есть: credit_pipeline agents, OSINT workflow, Order/OrderKind/User services. ~5 768 LOC, 117 файлов, 11 manifests.
* **Critical**: composition root падает на старте (P0-001, P0-002). Без фикса приложение не запустится.
* **Critical**: fail-open поведение в кредитном скоринге и OSINT (P0-003, P0-004).
* **Layer violations**: 1 прямой infrastructure import через `importlib` (P1-001), 2 soft violations через core-shim (P1-002).
* **Disconnected workflows**: 370 LOC в `orders_dsl.py` не доходят до runtime (P1-003); workflow YAML ссылается на несуществующие функции (P1-004).
* **Tests** покрывают scaffold и lifecycle; **отсутствуют** для `orders_dsl.py` (370 LOC без unit-тестов).
* **No direct infra/services imports** через `from/import` — verified. Dynamic import через `importlib.import_module` — единственный канал нарушения.
* **Capability gates** объявлены в plugin.toml для всех real extensions.

**Readiness = 0/100** (формула clamp). Реальная готовность с фиксами P0 — за 1-2 sprint'а до 70+.

---
*Отчёт создан: 2026-08-06, phase 1 / cycle 1. Не трогал source code, configs, lockfiles, allowlists. Не делал git mutation.*
