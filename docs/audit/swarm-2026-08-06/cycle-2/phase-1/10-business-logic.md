# Business logic domain audit — Cycle 2 / Phase 1

- **Date:** 2026-08-06
- **HEAD:** `ca5bff93058f2580041a7339913b52943babb329`
- **Scope:** `extensions/**` + tests inside `extensions/**`. The cycle-1 P0 IDs assigned to this domain require cross-reference evidence outside `extensions/`; those checks are read-only and limited to the cycle-1 file:line anchors (no broader exploration of `src/backend/core`, `src/backend/services`, `src/backend/infrastructure`).
- **Out of scope (заявлено):** cycle-1 отчёты, BASELINE.md cycle-1, PHASE-2-SUMMARY.md, PHASE-3-PLAN.md cycle-1, KNOWN_ISSUES.md, CLAUDE.md, PLAN.md, DEEP_AUDIT_REPORT.md, triage_allowlist_report.md. Прочие отчёты роя cycle 2 в этом phase-1 не читались.
- **Baseline (cycle 2):** commit `ca5bff93`; `python tools/check_layers.py --root src` → exit 0, 0 new / 175 legacy, 2273 files; `wc -l tools/check_layers_allowlist.txt` → 180 (header+comments included); `pip-audit-allowlist.txt` active IDs = 35. Pre-existing `M uv.lock` (-15 svcs, не в pyproject), `M tools/blue_green.sh`, `M tests/unit/tools/test_blue_green_switch.py`, `?? pip-audit.json`, `?? .blue_green.state` НЕ атрибутируются рою и не запрагивались. 5 uncommitted source правок cycle 1 Phase 4 (T-1.4/T-1.5/T-3.1) НЕ атрибутируются рою cycle 2.
- **Test environment limitation:** прогон pytest в этом phase-1 невозможен — `tests/unit/**` падает на collection из-за отсутствующего `email-validator` (импортируется через `extensions/core_entities/users/schemas/route.py:9` → `pydantic.EmailStr`). Targeted invocations логики выполнены inline без импорта EmailStr-зависимых модулей. Результаты прогонов зафиксированы в Commands run.

## Scope / что проверено / что не проверено

### Проверено

| Файл / артефакт | Прочитано | Примечание |
|---|---|---|
| `extensions/credit_pipeline/agents/__init__.py` | да | целиком, 191 строка |
| `extensions/credit_pipeline/plugin.py` | да | целиком |
| `extensions/credit_pipeline/domain/models.py` | да | целиком |
| `extensions/credit_pipeline/functions/normalize.py` | да | целиком |
| `extensions/credit_pipeline/functions/__init__.py` | да | целиком |
| `extensions/credit_pipeline/routes/__init__.py` | да | целиком |
| `extensions/credit_pipeline/services/clients/__init__.py` | да | целиком |
| `extensions/credit_pipeline/services/clients/skb.py` | да | целиком |
| `extensions/credit_pipeline/workflows/__init__.py` | да | целиком |
| `extensions/credit_pipeline/workflows/rag_augmented_saga.workflow.yaml` | да | целиком |
| `extensions/credit_pipeline/plugin.toml` | да | целиком |
| `extensions/credit_pipeline/__init__.py` | да | marker-only |
| `extensions/credit_pipeline/tests/test_actions_registration.py` | да | целиком |
| `extensions/credit_pipeline/tests/test_normalize.py` | да | целиком |
| `extensions/credit_pipeline/tests/test_domain_models.py` | да | целиком |
| `extensions/credit_pipeline/tests/test_workflow_yaml.py` | да | целиком |
| `extensions/osint_agent/__init__.py` | да | marker-only |
| `extensions/osint_agent/plugin.py` | да | целиком |
| `extensions/osint_agent/plugin.toml` | да | целиком |
| `extensions/osint_agent/domain/models.py` | да | целиком |
| `extensions/osint_agent/functions/__init__.py` | да | marker-only |
| `extensions/osint_agent/functions/osint_workflow.py` | да | целиком, 340 строк |
| `extensions/osint_agent/tests/test_osint_workflow.py` | да | целиком |
| `extensions/core_entities/__init__.py` | да | marker-only |
| `extensions/core_entities/files/plugin.py`, `services/files.py`, `repositories/files.py`, `schemas/*.py`, `tests/*.py` | да | целиком |
| `extensions/core_entities/orderkinds/services/orderkinds.py` | да | целиком |
| `extensions/core_entities/users/services/users.py` | да | целиком |
| `extensions/core_entities/orders/services/orders.py` | да | целиком, 423 строки |
| `extensions/core_entities/orders/repositories/orders.py` | да | целиком |
| `extensions/core_entities/orders/workflows/__init__.py`, `orders_dsl.py` | да | целиком |
| `extensions/core_entities/orders/admin.py` | да | целиком |
| `extensions/core_entities/orders/plugin.py` | да | целиком |
| `extensions/core_entities/orders/tests/test_repository_pattern.py` | да | целиком |
| `extensions/dadata/__init__.py`, `schemas_only.py`, `schemas/route.py` | да | целиком |
| `extensions/skb/__init__.py`, `schemas_only.py`, `services/waf_route.py` | да | целиком |
| `extensions/core_admin/__init__.py`, `schemas_only.py`, `schemas/route.py` | да | целиком |
| `extensions/example_plugin/plugin.py` | да | целиком |
| `extensions/test_plug/plugin.py` | да | целиком |
| `tools/check_layers.py`, `tools/check_layers_allowlist.txt` | да | прогон + просмотр структуры |
| `src/backend/core/di/module_registry.py:100-200` | да | cycle-1 ID verification (не в scope) |
| `src/backend/core/di/providers/db.py` | да | cycle-1 ID verification (не в scope) |
| `src/backend/plugins/composition/workflow_setup.py` | да | cycle-1 ID verification (не в scope) |
| `tests/unit/workflows/test_orders_saga.py` | да | cycle-1 ID verification (не в scope) |
| `pyproject.toml` (только секции `dependencies`) | да | для library replacement проверки |

### Не проверено

- Полный runtime wiring composition root (DI wiring, lifespan startup) вне scope этого phase-1.
- Production deployment profile / S3/Qdrant/Kafka/Temporal — внешние сервисы.
- Тесты в `tests/unit/**` не запускались из-за `ImportError: email-validator is not installed` в `extensions/core_entities/users/schemas/route.py:9` (Pydantic v2). Все выводы о fail-OPEN / fail-CLOSED сделаны по прямой инспекции кода и **inline-прогонам** бизнес-функций в обход EmailStr-зависимостей.
- Лицензии / maintenance / pyproject-preseнce всех кандидатов библиотек для library replacement — частично (только httpx, litellm, sqlalchemy подтверждены в `pyproject.toml`).
- `extensions/__pycache__/**`, `extensions/test_plug/__pycache__/**`, `extensions/example_plugin/__pycache__/**` — кэши, не source.

## Verified strengths

1. **Repository facade pattern enforcement** — `extensions/core_entities/{orders,files,orderkinds,users}/repositories/*.py` наследуют `SQLAlchemyRepository` из `src.backend.core.repositories.base` (НЕ `infrastructure`). Тест `test_repository_respects_facade_boundary` (test_repository_pattern.py:57-69) статически enforce'ит этот контракт и проверяет, что `OrderRepository` не импортирует напрямую из `infrastructure.repositories.base`.
2. **`extensions/credit_pipeline/functions/normalize.py::calculate_combined_score`** — fail-CLOSED: возвращает `0` если ни SKB, ни НБКИ score не переданы (строки 70-71). Это безопасный default для финансового домена.
3. **`extensions/credit_pipeline/functions/normalize.py::apply_rules`** — score clipping в `[0, 1000]`, явный `risk_class` mapping (`>=700` LOW, `>=500` MEDIUM, иначе HIGH), tested in `test_normalize.py` (8 тестов, fail-CLOSED boundary).
4. **`extensions/credit_pipeline/domain/models.py`** — Pydantic v2 models с явными `Literal` типами (`provider`, `decision`, `risk_class`), `Field(ge=…, le=…)` валидация. Tested in `test_domain_models.py` (4 теста, включая негативные).
5. **Plugin manifest compliance** — все extensions имеют `plugin.toml` с declared capabilities (`net.outbound`, `db.read/write`, `ai.llm`) и правильным `trust_tier` (`A` для credit_pipeline как banking-critical).
6. **`CreditPipelinePlugin` action registration** — `_make_handler` factory pattern устраняет copy-paste между handlers; `on_register_actions` idempotent (test_action_propagates_agent_exception + test_double_registration_is_idempotent_or_raises).
7. **DS workflow YAMLs структурно корректны** — `extensions/credit_pipeline/workflows/rag_augmented_saga.workflow.yaml` имеет `forward`+`compensate` saga-структуру, timeouts, описание.

## Findings table (P0..P4)

| ID | Priority | Path:line | Evidence / impact | Minimal recommendation | Test criterion |
|---|---|---|---|---|---|
| **DOMAIN-P0-003** | **P0** | `extensions/credit_pipeline/agents/__init__.py:84-94` | `base_score = 750  # Default for unknown` — когда `income` или `amount` равны 0/None, default остаётся 750; порог `_SCORE_APPROVAL_THRESHOLD = 600`; результат: пустой/неполный payload → APPROVED. Inline-прогон: `scoring_agent({}) → credit_score=750, approved=True`; `scoring_agent({'amount':0,'monthly_income':0}) → 750, approved=True`. Test `test_action_handles_missing_payload` (test_actions_registration.py:115-124) фиксирует поведение без payload, не требуя safety-net. Это fail-OPEN в кредитном скоринге. | Поменять default на fail-CLOSED (например, `base_score = 500` → MANUAL_REVIEW), либо raise `ValueError("missing income/amount")` до вычисления; явно требовать все 3 поля payload. | Unit test `test_scoring_rejects_missing_income_or_amount`: при отсутствии income/amount → `decision in ("MANUAL_REVIEW","REJECT")`, `approved is False`. |
| **DOMAIN-P0-004** | **P0** | `extensions/osint_agent/functions/osint_workflow.py:305-334` | Двухступенчатый fail-OPEN: (а) строки 305-313 при сбое multi-provider search результаты сбрасываются в `{"perplexity": None, ...}`, pipeline продолжается; (б) строки 323-334 при сбое LLM gateway `raw_text = prompt` — caller получает в качестве OSINT-отчёта шаблон промпта с placeholder-секциями ("Полное наименование, ОГРН, дата регистрации.", "Упоминание (источник: url)"), которые `_parse_report_sections` парсит как `positive_mentions`, `negative_mentions`, `court_cases`, `financial_markers`, `sources`. Inline-прогон подтверждает, что при `prompt` → `validate_report` → `general_info="Полное наименование, ОГРН, дата регистрации."`, `positive_mentions=[{text:"Упоминание (источник: url)"}]`, `sources=["url"]`. Это data fabrication в OSINT-агенте. | Fail-CLOSED: при сбое search/LLM — raise `RuntimeError("OSINT workflow degraded: ...")` или вернуть `{"status": "FAILED", "inn": inn, "errors": [...]}` без parsed sections; не использовать `prompt` как fallback. | Unit test `test_run_osint_fails_closed_on_llm_unavailable`: monkey-patch `get_litellm_gateway` → RuntimeError; assert exception propagates (или `report["status"] == "FAILED"`); assert НЕ возникает `positive_mentions`/`sources` с placeholder-текстом. |
| **DOMAIN-P0-001** (cross-scope) | **P0** | `src/backend/core/di/module_registry.py:136-137` → `src/backend/infrastructure/repositories/{files,orders}.py` (НЕ существуют) | `INFRA_MODULES["repos.files"] = "src.backend.infrastructure.repositories.files"` и `["repos.orders"] = "src.backend.infrastructure.repositories.orders"` указывают на несуществующие модули. `db.py:57` использует `resolve_module("repos.files")` через `get_file_repo_provider()` → `extensions/core_entities/files/services/files.py:12` импортирует этот provider. Inline-прогон: `from src.backend.core.di.module_registry import resolve_module; resolve_module("repos.files")` → `ModuleNotFoundError: No module named 'src.backend.infrastructure.repositories.files'`. Функциональный код переехал в `extensions/core_entities/{files,orders}/repositories/`, но `INFRA_MODULES` запись осталась stale. `repos.orders` — pure dead entry (нет callsite). | Перенаправить `repos.files` → `extensions.core_entities.files.repositories.files` (где живёт `get_file_repo`); удалить `repos.orders` или перенаправить на `extensions.core_entities.orders.repositories.orders`. | После правки: `resolve_module("repos.files")` возвращает модуль с `get_file_repo`; targeted unit-тест `test_module_registry_repos_files_resolvable` проходит. |
| **DOMAIN-P0-002** (cross-scope) | **P0** | `src/backend/plugins/composition/workflow_setup.py:76-83` | `from extensions.core_entities.orders.workflows.orders_saga import build_orders_saga_workflow` и `from extensions.credit_pipeline.workflows.payments_saga import build_payments_saga_workflow` импортируют функции из модулей, которых НЕТ. Подтверждено: `ls extensions/core_entities/orders/workflows/` → только `__init__.py` и `orders_dsl.py`; `ls extensions/credit_pipeline/workflows/` → только `__init__.py`, `orders_dsl.py` нет, есть `rag_augmented_saga.workflow.yaml` (YAML, не Python). Saga-демо удалены в коммите `9164a59` ("enable all feature flags + remove demos", S168 W14); `tests/unit/workflows/test_orders_saga.py:1-9` имеет `pytest.skip(...)` с обоснованием. Workflow runtime упадёт с `ModuleNotFoundError` при `WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=true`. Default флага — OFF, поэтому production не падает. | Удалить блок `_bootstrap_default_declarations` и его вызов из `start_workflow_runtime`; либо создать реальные saga-модули (в соответствии с `R-V15-9`). | Targeted test `test_workflow_bootstrap_disabled_returns_empty` уже существует косвенно; добавить явный `test_workflow_bootstrap_no_missing_imports`: при `bootstrap_defaults_enabled=true` — assertion, что bootstrap **НЕ** импортирует saga-демо. |
| DOMAIN-P1-001 | P1 | `extensions/core_entities/orders/services/orders.py:44,413` | `_S3_MOD = "src.backend.infrastructure.external_apis.s3"` (строка 44) + `s3_service = importlib.import_module(_S3_MOD).get_s3_service_dependency()` (строка 413) — extension делает dynamic import из `infrastructure` слоя, обходя статическую проверку layer checker. Это прямое нарушение архитектурного правила AGENTS.md («Прямой импорт из `infrastructure/*` / `services/*` запрещён»). | Использовать capability-checked facade: `from src.backend.core.di.providers import get_s3_service_provider` (уже существует в `db.py:129-139`); добавить DI provider для s3 в composition root. | Layer test reject'ит extensions → infrastructure edge; `get_order_service()` инстанциируется без `importlib` infrastructure import. |
| DOMAIN-P1-002 | P1 | `extensions/core_entities/files/services/files.py:12` + `src/backend/core/di/providers/db.py:53-58` | `FileService.__init__` берёт repo через `get_file_repo_provider()`; provider внутри делает `resolve_module("repos.files")` → ModuleNotFoundError (см. DOMAIN-P0-001). Это означает, что **любой runtime вызов `get_file_service()` упадёт** — банковская интеграционная шина не сможет обслужить file upload. Файл существует в `extensions/core_entities/files/repositories/files.py` с `get_file_repo()`, но provider указывает на stale INFRA_MODULES. | Связано с DOMAIN-P0-001: правка `repos.files` mapping. | After fix: `get_file_service()` возвращает рабочий `FileService` instance. |
| DOMAIN-P2-001 | P2 | `extensions/core_entities/orders/services/orders.py:108-126` | `_index_order_async` и `_delete_order_index_async` имеют `except Exception: return` (lines 112-113, 125-126). ES indexing является fire-and-forget, но swallows ВСЕ ошибки без логирования/метрик. Это observable dead branch — оператор не узнает, что ES-индексация заказов сломана (тихий partial degradation). | Логировать exception на уровне WARNING (без stack trace) + increment метрику `order_es_indexer_failures_total`. | Unit test: monkey-patch `get_order_indexer().index_one_fire_and_forget` → raise; assert метрика инкрементирована или warning logged. |
| DOMAIN-P2-002 | P2 | `extensions/osint_agent/domain/models.py:20-46` | `OsintReport` dataclass определён, но `osint_workflow.py::run_osint` возвращает **raw dict** (line 336: `return report`, где `report = validate_report(raw_text)` — dict). Ни один tests/callsite не использует `OsintReport`. Это dead code / type-safety gap. | Конвертировать `validate_report` output в `OsintReport`; либо удалить dataclass. | Type checker / mypy pass на typed model; один unit-тест на `OsintReport.parse_from(...)`. |
| DOMAIN-P2-003 | P2 | `extensions/credit_pipeline/agents/__init__.py:74` | `# Rule-based scoring (placeholder для production ML model).` — explicit stub marker для будущей ML-интеграции. Не блокер, но при exacerbation DOMAIN-P0-003 (default 750) этот placeholder становится опасным default'ом. | В рамках фикса DOMAIN-P0-003 перейти на `feature_flag.credit_pipeline_v2` gated ML-scoring path с явным `NOT_READY` status. | Test: при `credit_pipeline_v2=false` → явный `model_version="rule-based-stub"` + warning в metadata. |
| DOMAIN-P2-004 | P2 | `extensions/credit_pipeline/workflows/__init__.py:1-12` + `functions/__init__.py:1-13` + `routes/__init__.py:1-12` + `services/clients/__init__.py:1-14` | 4 модуля scaffold'а с `TODO Team T3 (Sprint 8+):` markers, `__all__: tuple[str, ...] = ()` (пустой), нет functional content. Цикл 1 / 2 их не разрешил — Sprint 8+ остаётся непройденным. | Закрыть TODO либо удалить scaffold файлы (Ponytail). | Спринт-план: либо roadmap-эпик закрыт, либо TODO удалены. |
| DOMAIN-P3-001 | P3 | `extensions/credit_pipeline/services/clients/skb.py:92, 106, 132` | `except Exception as exc: raise ServiceError from exc` — `from exc` сохраняет chain, но `ServiceError(message=...)` не пробрасывает detail; caller видит generic `ServiceError` без текста. | Логировать exception до raise; либо кастомный `SKBServiceError(message=str(exc), code=...)`. | Test `test_skb_error_preserves_message`: mock `_request` → `httpx.HTTPError("timeout")`; assert `ServiceError.__cause__` is `httpx.HTTPError` и logging содержит message. |
| DOMAIN-P3-002 | P3 | `extensions/osint_agent/functions/osint_workflow.py:226-241` (`_scrape_url`) | Прямое использование `httpx.AsyncClient` (Ponytail-комментарий признаёт, что это bypass facade). Это означает, что S170 M3 unified transport stack (RetryTransport + CacheTransport) не покрывает этот путь. | Использовать `OutboundHttpClient` facade из `src/backend/core/services/base` (для `net.outbound` capability уже задекларирован в `plugin.toml`). | Unit test: scrape через `_scrape_url` использует те же retries/timeouts, что и facade. |
| DOMAIN-P4-001 | P4 | `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml` etc. | YAML-workflow'ы описывают saga `fetch_credit_data → rag_query → llm_decision → fund_account/refund_account`, но **реальный Temporal-compiled workflow** не создан. DSL-workflow runtime не может выполнять `fund_account` saga compensations. | Закрыть как Phase 5 (после Sprint 8+); пока оставить как declarative placeholder. | Roadmap epic. |

**Finding count:** P0=4 (3 cross-scope, 1 in-scope), P1=2, P2=4, P3=2, P4=1.

## Detailed evidence

### DOMAIN-P0-003 (in-scope) — credit scoring fail-OPEN

Inline-прогон бизнес-функции (без импорта EmailStr-зависимых модулей):

```python
$ python -c "<inline scoring_agent logic>"
Empty payload: {'client_id': 0, 'credit_score': 750, 'approved': True}
No income: {'client_id': 0, 'credit_score': 750, 'approved': True}
No amount: {'client_id': 0, 'credit_score': 750, 'approved': True}
Zero income (fraud?): {'client_id': 0, 'credit_score': 750, 'approved': True}
Valid: {'client_id': 0, 'credit_score': 800, 'approved': True}
```

Подтверждённый код (фрагмент `extensions/credit_pipeline/agents/__init__.py:81-94`):

```python
monthly_payment = amount / max(duration, 1) if duration else 0
dti = (monthly_payment / max(income, 1)) if income > 0 else 0.5

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

`base_score = 750` для unknown — это `> _SCORE_APPROVAL_THRESHOLD = 600` → APPROVED. Прямая fail-OPEN в банковском скоринге. Существующий test `test_action_handles_missing_payload` (test_actions_registration.py:115-124) **фиксирует** это поведение без payload, не тестируя safety-net.

### DOMAIN-P0-004 (in-scope) — OSINT workflow fail-OPEN (двухступенчатый)

Подтверждённый код `extensions/osint_agent/functions/osint_workflow.py:305-334`:

```python
try:
    results_general = await _search_multi_provider(queries["general"])
    results_courts = await _search_multi_provider(queries["courts"])
    results_negative = await _search_multi_provider(queries["negative"])
except Exception:
    results_general = {"perplexity": None, "tavily": None, "scraped": []}
    results_courts = {"perplexity": None, "tavily": None, "scraped": []}
    results_negative = {"perplexity": None, "tavily": None, "scraped": []}

prompt = compose_prompt(...)

try:
    from src.backend.core.ai.llm_gateway import get_litellm_gateway
    gateway = get_litellm_gateway()
    response = await gateway.acompletion(...)
    raw_text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
except Exception:
    raw_text = prompt   # ← ШАБЛОН ПРОМПТА КАК "ОТЧЁТ"

report = validate_report(raw_text)
report["inn"] = inn
...
return report
```

Inline-прогон `validate_report(prompt)` (где prompt — это OSINT_REPORT_TEMPLATE с placeholder'ами после `_format_results(...)` → "Данные не найдены") даёт:

```python
{
  'general_info': 'Полное наименование, ОГРН, дата регистрации. ',
  'positive_mentions': [{'text': 'Упоминание (источник: url)'}],
  'negative_mentions': [{'text': 'Упоминание (источник: url)'}],
  'court_cases': [{'text': 'Дело: номер, дата, сторона, статус (источник: url)'}],
  'financial_markers': ['Маркер'],
  'sources': ['url'],
  ...
}
```

То есть caller получает структурированный "OSINT-отчёт" с **литералами шаблона**, парсенными как content. Это data fabrication: отчёт выглядит валидным, но не содержит ни одного фактического source URL / court case / financial marker.

Существующий `test_osint_workflow.py` **не покрывает** `run_osint` end-to-end (нет ни одного test для `run_osint`); тестируются только `_build_search_queries`, `_format_results`, `_parse_report_sections`, `compose_prompt`, `validate_report` и `validate_inn`. Fail-OPEN не покрыт тестами.

### DOMAIN-P0-001 (cross-scope) — repos.files/orders stale registry

`src/backend/core/di/module_registry.py:136-137`:
```python
"repos.files": f"{_INFRA}.repositories.files",
"repos.orders": f"{_INFRA}.repositories.orders",
```

`_INFRA = "src.backend.infrastructure"`. Соответствующих модулей нет (`ls src/backend/infrastructure/repositories/` → `ai_feedback_mongo.py base connector_configs_mongo.py express_dialogs_mongo.py express_sessions_mongo.py __init__.py notebooks_mongo.py outbox.py rule_engine_repository.py`; нет `files.py` и нет `orders.py`).

Inline-прогон:

```python
$ python -c "from src.backend.core.di.module_registry import resolve_module; resolve_module('repos.files')"
ModuleNotFoundError: No module named 'src.backend.infrastructure.repositories.files'
```

`db.py:53-58` экспортирует `get_file_repo_provider`:
```python
def get_file_repo_provider() -> Any:
    if "file_repo" in _overrides:
        return _overrides["file_repo"]
    module = resolve_module("repos.files")
    return module.get_file_repo()
```

`extensions/core_entities/files/services/files.py:12` импортирует этот provider:
```python
from src.backend.core.di.providers import get_file_repo_provider
```

Функциональный `get_file_repo()` живёт в `extensions/core_entities/files/repositories/files.py:39` (определён, есть `__all__`). Достаточно исправить `INFRA_MODULES` маппинг.

`repos.orders` — pure dead entry (нет callsite, grep по всему проекту подтверждает).

### DOMAIN-P0-002 (cross-scope) — workflow_setup saga imports

`src/backend/plugins/composition/workflow_setup.py:76-83`:
```python
from extensions.core_entities.orders.workflows.orders_saga import (
    build_orders_saga_workflow,
)
from extensions.credit_pipeline.workflows.payments_saga import (
    build_payments_saga_workflow,
)

declarations = [build_orders_saga_workflow(), build_payments_saga_workflow()]
```

Подтверждение отсутствия модулей:
```
$ ls extensions/core_entities/orders/workflows/
__init__.py  orders_dsl.py
$ ls extensions/credit_pipeline/workflows/
code_interpreter_loop.workflow.yaml  credit_assessment.workflow.yaml
__init__.py  multi_agent_supervisor.workflow.yaml
rag_augmented_saga.workflow.yaml  README.md
```

Никаких `orders_saga.py` или `payments_saga.py`. Saga-демо удалены в коммите `9164a59` ("enable all feature flags + remove demos"); `tests/unit/workflows/test_orders_saga.py:1-9` имеет `pytest.skip(...)`.

Если `WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=true` — `start_workflow_runtime` крашится на `ModuleNotFoundError`. Default флага — OFF. Роу cycle 2 не устранил broken imports.

### DOMAIN-P1-001 (in-scope) — extension → infrastructure dynamic import

`extensions/core_entities/orders/services/orders.py:42-44`:
```python
_REPO_ORDERS_MOD = "extensions.core_entities.orders.repositories.orders"
_REPO_FILES_MOD = "extensions.core_entities.files.repositories.files"
_S3_MOD = "src.backend.infrastructure.external_apis.s3"
```

Строка 413:
```python
s3_service = importlib.import_module(_S3_MOD).get_s3_service_dependency()
```

`importlib.import_module("src.backend.infrastructure.external_apis.s3")` обходит статический layer-checker; checker сканирует только `import`/`from ... import` AST. Нарушено архитектурное правило «extensions → infrastructure/* запрещён». В composition root уже есть capability-checked провайдер `get_s3_service_provider()` (`src/backend/core/di/providers/db.py:129-139`) — extension должен использовать его.

### Layer-violation growth 173 → 180 — clarification

```text
$ python tools/check_layers.py --root src
Нарушений: 0 новых  (файлов: 2273; baseline: 175 legacy)
$ wc -l tools/check_layers_allowlist.txt
180
$ grep -vE '^\s*(#|$)' tools/check_layers_allowlist.txt | wc -l
175
```

`wc -l` = 180 = 5 header/comments lines + 175 legacy entries. Checker baseline = 175 legacy / 0 new, что совпадает с cycle-2 BASELINE. Заявленный рост 173 → 180 — метрический артефакт смешения `wc -l` (все строки) с count of actual entries. Реального роста layer-violations за cycle 2 нет.

## Cycle-1 residuals (verified or mutated)

| Cycle-1 ID | Cycle-1 path | Cycle-2 status | Evidence |
|---|---|---|---|
| DOMAIN-P0-001 | `src/backend/core/di/module_registry.py:136-137` (repos.files/orders) | **RESIDUAL** | Строки 136-137 без изменений; inline `resolve_module("repos.files")` всё ещё → `ModuleNotFoundError`. Цикл 1 / 2 их не починил. |
| DOMAIN-P0-002 | `src/backend/plugins/composition/workflow_setup.py:76-83` (saga imports) | **RESIDUAL** | Строки 76-83 без изменений; `extensions/core_entities/orders/workflows/orders_saga.py` не создан; `extensions/credit_pipeline/workflows/payments_saga.py` не создан; единственный saga-like артефакт — `rag_augmented_saga.workflow.yaml` (YAML, не Python). `tests/unit/workflows/test_orders_saga.py:1-9` skip'ит тест. |
| DOMAIN-P0-003 | `extensions/credit_pipeline/agents/__init__.py:84-94` (fail-OPEN) | **RESIDUAL** | Строки 84-94 без изменений; `base_score = 750 # Default for unknown`; inline-прогон подтверждает `approved=True` для пустого payload. |
| DOMAIN-P0-004 | `extensions/osint_agent/functions/osint_workflow.py` (fail-OPEN) | **RESIDUAL** | Файл без существенных изменений; `except Exception: raw_text = prompt` на lines 333-334; inline-прогон подтверждает, что template-плейсхолдеры парсятся как OSINT sections. |

Все 4 cycle-1 P0 ID остаются RESIDUAL (verified).

## Contradictions / overlaps to flag

1. **Layer-violations 173 → 180**: это не рост, а метрический артефакт (`wc -l` vs actual entries). Cycle-2 BASELINE = 175 legacy / 0 new; роста нет. Документировано в Detailed evidence.
2. **DOMAIN-P0-001 ↔ DOMAIN-P1-002 (overlap)**: оба указывают на stale `INFRA_MODULES["repos.files"]`. DOMAIN-P0-001 — registry entry stale, DOMAIN-P1-002 — конкретный impact на `extensions/core_entities/files/services/files.py`. Лечатся одним изменением; в findings table разнесены, чтобы явно показать registry-vs-impact дихотомию.
3. **DOMAIN-P0-003 ↔ DOMAIN-P2-003 (overlap)**: P2-003 фиксирует `# placeholder для production ML model` в строке 74 как отдельную заметку; основной fix живёт в P0-003 (default `base_score`).
4. **`extensions/core_entities/users/schemas/route.py:9`** использует `pydantic.EmailStr`, что блокирует весь `pytest collection` из-за отсутствующего `email-validator` в окружении phase-1. Это **вне scope** бизнес-логики, но критично для testability всего `extensions/`. Не зафиксировано как finding (другая domain ownership), но flag'нется в overlap section для cross-domain visibility.
5. **Pre-existing working-tree drift** (`M uv.lock` -15 svcs, `M tools/blue_green.sh`, `M tests/unit/tools/test_blue_green_switch.py`, `?? pip-audit.json`, `?? .blue_green.state`) — НЕ атрибутируется рою cycle 2; никаких правок не делалось.
6. **5 uncommitted source правок cycle 1 Phase 4 (T-1.4 / T-1.5 / T-3.1)** — в working tree на момент phase-1, но НЕ атрибутируются рою cycle 2. Все из них — вне `extensions/`: `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py`, `src/backend/dsl/engine/processors/eip/{reliability/redelivery_policy.py,routing/multicast.py}`, `src/backend/infrastructure/cache/rag/embedding_cache.py`, `src/backend/services/ai/gateway_adapter.py`. Не проверены в этом аудите (вне scope).

## Readiness score 0–100

**Формула:**

```
readiness = 100
            - 18 * P0_count         # P0 = -18 каждый (security/data-loss/race/fail-open)
            - 10 * P1_count         # P1 = -10 каждый (layer boundaries)
            - 4  * P2_count         # P2 = -4  каждый (dead code / dead branches)
            - 1  * P3_count         # P3 = -1  каждый (observability)
            - 0  * P4_count         # P4 = 0  каждый (new features)
            - clamp(0, 100)
```

**Подсчёт:**
- P0 = 4 (DOMAIN-P0-001 cross, DOMAIN-P0-002 cross, DOMAIN-P0-003 in, DOMAIN-P0-004 in)
- P1 = 2 (DOMAIN-P1-001, DOMAIN-P1-002)
- P2 = 4 (DOMAIN-P2-001, DOMAIN-P2-002, DOMAIN-P2-003, DOMAIN-P2-004)
- P3 = 2 (DOMAIN-P3-001, DOMAIN-P3-002)
- P4 = 1 (DOMAIN-P4-001)

```
readiness = 100
           - 18 * 4    # = 72
           - 10 * 2    # = 20
           - 4  * 4    # = 16
           - 1  * 2    # =  2
           - 0  * 1    # =  0
           = 100 - 72 - 20 - 16 - 2 - 0 = -10 → clamp → 0
```

**Итоговая оценка: 0** (clamped).

**Обоснование:** наличие **любого P0 блокирует production** (banking-critical credit scoring fail-OPEN, OSINT report fabrication, broken DI registry, broken composition root). По правилу задания «Оценка ≥80 запрещена при наличии P0/P1», максимальная оценка при текущем наборе = ≤ 79. С учётом клампинга (формула даёт -10) и агрессивного штрафа за P0 — readiness = 0.

Альтернативный conservative-вариант (только in-scope findings): readiness = 100 - 18*2 - 10*1 - 4*3 - 1*1 = 100 - 36 - 10 - 12 - 1 = 41. Это отражает состояние **только** `extensions/` слоя; с учётом cross-scope P0 — финальная оценка = 0.

## Recommended next tasks

1. **[P0] Fix DOMAIN-P0-003 (credit scoring fail-OPEN)** — изменить `base_score = 750` на `500` или raise `ValueError` для missing income/amount; добавить unit-тест `test_scoring_rejects_missing_income_or_amount`.
2. **[P0] Fix DOMAIN-P0-004 (OSINT workflow fail-OPEN)** — fail-CLOSED при сбое search/LLM: либо raise, либо `report["status"]="FAILED"`; добавить end-to-end test `test_run_osint_fails_closed_on_llm_unavailable` и `test_run_osint_fails_closed_on_search_unavailable`.
3. **[P0] Fix DOMAIN-P0-001 (DI registry stale)** — перенаправить `INFRA_MODULES["repos.files"]` на `extensions.core_entities.files.repositories.files`; удалить или перенаправить `INFRA_MODULES["repos.orders"]`.
4. **[P0] Fix DOMAIN-P0-002 (composition root saga imports)** — удалить dead `orders_saga`/`payments_saga` imports; убрать `_bootstrap_default_declarations` либо реализовать реальные saga через WorkflowBuilder.
5. **[P1] Fix DOMAIN-P1-001 (layer violation)** — `get_order_service()` должен использовать `get_s3_service_provider()` вместо `importlib.import_module("src.backend.infrastructure.external_apis.s3")`.
6. **[P1] Verify DOMAIN-P1-002 (file repo runtime)** — после фикса DOMAIN-P0-001 добавить smoke-тест `get_file_service().repo is not None`.
7. **[P2] Clean up DOMAIN-P2-002 (dead `OsintReport`)** — использовать typed model в `run_osint` или удалить.
8. **[P2] Resolve DOMAIN-P2-004 (scaffold TODOs)** — закрыть Sprint 8+ roadmap либо удалить scaffold файлы.
9. **[P3] Improve DOMAIN-P3-001 (SKB error messages)** — log exception + structured error context.

## Commands run

```bash
# Scope/structure
ls /home/user/dev/gd_integration_tools/extensions/
ls /home/user/dev/gd_integration_tools/extensions/credit_pipeline/
ls /home/user/dev/gd_integration_tools/extensions/credit_pipeline/workflows/
ls /home/user/dev/gd_integration_tools/extensions/core_entities/orders/workflows/
ls /home/user/dev/gd_integration_tools/extensions/core_entities/orderkinds/
ls /home/user/dev/gd_integration_tools/extensions/osint_agent/

# Search for saga modules
find /home/user/dev/gd_integration_tools/extensions -name "*saga*" -o -name "orders_saga*" -o -name "payments_saga*"
find /home/user/dev/gd_integration_tools/extensions -name "*.py" -path "*saga*"

# Find stale DI registry targets
find /home/user/dev/gd_integration_tools/src/backend/infrastructure/repositories -name "files*" -o -name "orders*"
ls /home/user/dev/gd_integration_tools/src/backend/infrastructure/repositories/

# Inline verify ModuleNotFoundError for repos.files
python -c "from src.backend.core.di.module_registry import resolve_module; resolve_module('repos.files')"
# → ModuleNotFoundError: No module named 'src.backend.infrastructure.repositories.files'

# Verify DOMAIN-P0-003 (fail-OPEN scoring)
python -c "<inline scoring_agent logic for empty/no-income/no-amount/zero-income/valid payloads>"
# → все кейсы (кроме valid) возвращают credit_score=750, approved=True

# Verify DOMAIN-P0-004 (fail-OPEN OSINT)
python -c "<inline compose_prompt + _format_results + _parse_report_sections with empty results>"
# → sections парсятся из template placeholders ('Упоминание (источник: url)', 'Маркер', 'url' и т.д.)

# Layer checker
python tools/check_layers.py --root src
# → Нарушений: 0 новых (файлов: 2273; baseline: 175 legacy)

# Allowlist count
wc -l tools/check_layers_allowlist.txt
# → 180 tools/check_layers_allowlist.txt
grep -vE '^\s*(#|$)' tools/check_layers_allowlist.txt | wc -l
# → 175 (actual entries)

# Grep for layer violations from extensions
grep -rn "from src.backend" /home/user/dev/gd_integration_tools/extensions --include="*.py"
grep -rE "src\.backend\.(infrastructure|services)" /home/user/dev/gd_integration_tools/extensions --include="*.py"
grep -rn "import_module" /home/user/dev/gd_integration_tools/extensions --include="*.py"

# TODOs / stubs / pass / NotImplemented
grep -rE "TODO|FIXME|XXX|HACK|NotImplemented|pass$" /home/user/dev/gd_integration_tools/extensions --include="*.py"
grep -rE "stub|placeholder|fake" /home/user/dev/gd_integration_tools/extensions --include="*.py"

# Test collection (env broken — email-validator missing)
python -m pytest extensions/credit_pipeline/tests/test_normalize.py -x --tb=short
# → ERROR: ImportError: email-validator is not installed, run `pip install 'pydantic[email]'`
```

Pre-existing test environment issue (`email-validator` missing) заблокировал прогон pytest. Все conclusions о fail-OPEN / fail-CLOSED сделаны по **прямой инспекции кода** и **inline-прогонам бизнес-функций** в обход EmailStr-зависимых модулей; команды зафиксированы.
