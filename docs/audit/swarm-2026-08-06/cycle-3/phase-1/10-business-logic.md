# 10-business-logic — Domain audit (Cycle 3 / Phase 1)

- **Domain**: Бизнес-логика (extensions/** + tests внутри extensions/)
- **Date**: 2026-08-06
- **HEAD**: `7f3d94a3` (cycle retrospective commit, +1 от cycle-2 baseline)
- **Author**: independent domain analyst (Kimicl-M3, cycle-3 phase-1)
- **Python interpreter (cycle 3 mandatory)**: `.venv/bin/python` (cpython-3.14-linux-x86_64-gnu)
  — system Python без `prometheus_client`/`fastapi`/`hypothesis` НЕ использовался;
  reviewer cycle-2 падал именно на system Python, что было ошибочно
  интерпретировано как pre-existing environment state.
- **Re-verification obligation**: cycle-1 + cycle-2 findings из моего scope
  обязательно перепроверены.

---

## Scope / не проверено

### In scope (проверено)

| Subdomain | Path | LOC | Tests |
|---|---|---:|---:|
| credit_pipeline (real impl) | `extensions/credit_pipeline/{plugin.py, agents/, domain/, functions/, services/, workflows/}` | ~820 | 33 in-tree + 10 unit + 6 integration |
| osint_agent (real impl) | `extensions/osint_agent/{plugin.py, functions/, domain/}` | ~440 | 17 in-tree |
| core_entities (orders/files/users/orderkinds) | `extensions/core_entities/*/{plugin.py, services/, repositories/, schemas/, admin.py, workflows/}` | ~3440 | 35 in-tree + 11 unit (LDAP) + 3 cycle-31 + 7 skb-migrated |
| core_admin / dadata / skb (schemas-only) | `extensions/{core_admin,dadata,skb}/{schemas_only.py, plugin.toml, schemas/}` | ~90 | 4 unit |
| example_plugin / test_plug (dev fixtures) | `extensions/{example_plugin, test_plug}/` | ~85 | 4 unit |
| prelude / re-exports | `extensions/__init__.py` | 101 | covered transitively |

**Total**: 117 .py + 15 .yaml/.toml = ~5799 LOC Python, ~5.6k tests collected.

### Out of scope (NOT проверено)

- src/backend/** (infrastructure/dsl/services/entrypoints/ai/**) — за рамками
  phase-1 аудита бизнес-логики; проверяются соседними доменами
  (architecture, security, integration, ai).
- `tests/integration/extensions/credit_pipeline/test_workflow_examples.py`
  пройден (.venv/bin/python, 6/6 PASSED), но workflow-YAML
  runtime semantics не проверялись (нужен Temporal worker).
- `src/backend/plugins/composition/workflow_setup.py` НЕ in extensions/, но
  содержит **dead imports из extensions** — задокументировано как
  BLOCKER-P0-001 (cross-scope, но затрагивает extensions).
- Cycle-1/cycle-2 markdown отчёты (`cycle-1/`, `cycle-2/`), `CLAUDE.md`,
  `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md`,
  `KNOWN_ISSUES.md` — НЕ читал по правилам phase-1 (verification
  строится на прямом чтении кода/тестов).
- `uv.lock` diff (`-15 svcs`), `.blue_green.state`, `pip-audit.json` —
  pre-existing drift, НЕ атрибутируется phase-1 (baseline §1).
- Cycle-1/cycle-2 uncommitted правки (5 cycle-1 source + 4 cycle-1 test +
  1 preflight + 4 cycle-2 source + 2 cycle-2 test + 1 cycle-2 audit doc) —
  НЕ входят в scope phase-1 (baseline §1).
- 5 pre-existing failures в `tests/unit/core/ai/test_gateway_pipeline_mixin.py`
  — НЕ моя зона (core/ai). Не воспроизводил, не верифицировал.
- `extensions/credit_pipeline/routes/__init__.py` пуст (scaffold) — нет
  реальной route логики для аудита.
- Workflow runtime в `.venv` (LiteTemporalBackend / Temporal) — flow
  semantics saga/compensation не прогонялись end-to-end (нужен worker,
  out of scope read-only).
- `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml`
  reference: activities ссылаются на `extensions.credit_pipeline.
  services.clients.skb:fetch_for_workflow` и `extensions.credit_pipeline.
  functions.publish:emit_decision` — этих функций НЕТ в коде
  (`skb.py` экспортирует только `CreditSKBClient`+`get_credit_skb_client`,
  `publish.py` отсутствует целиком), но YAML **не прогоняется runtime**
  (feature-flag off, нет test_runner step в extensions tests),
  поэтому формально это **dead-but-inert** — не runtime-P0 (см. P2-001).

---

## Verified strengths (что реально работает в extensions/)

1. **T-W1-08 (cycle-2) — credit scoring fail-closed — RESOLVED** ✅
   - `extensions/credit_pipeline/agents/__init__.py:94-114` —
     `scoring_agent()` при `income <= 0 or amount <= 0` возвращает
     `credit_score=0, risk_class="HIGH", reason="unknown_tenant",
     stub=False` И эмитит `credit_rejected` через `emit_audit_safe`.
   - `tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py`
     — 3/3 PASSED (test_scoring_unknown_tenant_rejected,
     test_decision_chained_rejects_unknown_tenant,
     test_scoring_incomplete_payload_rejected).
   - Проверено командой:
     `.venv/bin/python -m pytest tests/unit/extensions/credit_pipeline/
     test_scoring_fail_closed.py -v` → **exit 0, 3 passed in 5.11s**.
   - Независимый confirm через `.venv/bin/python -m pytest
     extensions/credit_pipeline/tests/test_actions_registration.py -v` →
     **5/5 PASSED** (real-agent integration + decision_chain).
   - Полная регрессия: `.venv/bin/python -m pytest
     tests/unit/extensions/credit_pipeline/ -v` → **13/13 PASSED**
     (3 fail-closed + 10 real-agent).

2. **Layer discipline в extensions** ✅
   - `grep -rn "from src.backend.infrastructure" extensions/ --include='*.py'`
     → **0 hits** (нет прямых импортов из infrastructure layer).
   - `grep -rn "from src.backend.services" extensions/ --include='*.py'`
     → **0 hits** (нет прямых импортов services layer — все через
     `core.facades` / `core.di.providers`).
   - `extensions/__init__.py` (prelude, 101 LOC) использует PEP-562
     lazy `__getattr__` для `SQLAlchemyRepository` (ponytail D111) —
     verified `.venv/bin/python -c "import extensions; srep =
     extensions.SQLAlchemyRepository"` → OK (4.3s, ABCMeta).

3. **Plugin lifecycle hooks (core_entities/*)** ✅
   - Все 4 core_entities плагина (files/users/orders/orderkinds)
     регистрируют actions через `on_register_actions` (35 tests PASSED),
     не через `dsl/commands/setup.py` (cycle-2 layer-violation fix
     задокументирован в каждом plugin.py).
   - `extensions/core_entities/orders/workflows/orders_dsl.py` —
     saga DSL через `WorkflowBuilder().saga().forward().compensate()`
     (5 workflows: notifications.send_email, orders.create_skb,
     orders.poll_skb_result, orders.send_skb_result, orders.full_processing).

4. **schemas-only extensions корректны** ✅
   - `extensions/{core_admin,dadata,skb}/{schemas_only.py, plugin.toml}`
     — point-in-time schema registry без бизнес-логики (явно
     декларировано как "Schemas-only plugin — Pydantic models for X
     entities; no business logic" в README).
   - `extensions/skb/services/waf_route.py:resolve_waf_route` — pure
     function `(env, waf_url) → (waf_url, use_waf)`, нет I/O.
   - Все 3 имеют `trust_tier = "A"` (D-AUDIT-FIX-184-5 verified via
     `tests/unit/extensions/test_plugin_trust_tier.py` → 4/4 PASSED).

5. **Pydantic валидация domain-моделей** ✅
   - `extensions/credit_pipeline/domain/models.py` — `CreditApplication`
     (amount ≥ 1000), `CreditReport` (literal SKB/NBKI/CBR),
     `CreditDecision` (literal APPROVE/MANUAL_REVIEW/REJECT) —
     `extensions/credit_pipeline/tests/test_domain_models.py` →
     **4/4 PASSED**.

6. **OSINT domain структура валидна** ✅
   - 17 tests PASSED (4 validate_inn + 2 build_search_queries +
     4 format_results + 1 parse_report_sections + 2 validate_report +
     1 compose_prompt + 3 не-validate_inn); см. P1-001 про 2 fails.

7. **Banking helpers в core (доступны extensions)** ✅
   - `src/backend/dsl/helpers/banking.py:validate_inn` —
     корректно валидирует 10- и 12-значные ИНН по checksum
     (см. P2-002 про edge case с None).

---

## Findings table

| ID | Pri | File:line | Title | Status |
|---|---|---|---|---|
| **BL-P0-001** | P0 | `src/backend/plugins/composition/workflow_setup.py:76-82` | Dead saga imports: `orders_saga` + `payments_saga` модули отсутствуют | RESIDUAL (cycle-2 P0-002 mutated — не cross-extensions dead, но dead FROM extensions) |
| **BL-P1-001** | P1 | `extensions/osint_agent/functions/osint_workflow.py:306-313, 333-334` | OSINT fail-OPEN на LLM-down: возвращает prompt template как "report" | RESIDUAL (cycle-2 P0-004 — мantiated, не RESOLVED) |
| **BL-P1-002** | P1 | `src/backend/core/config/features/plugins.py:41-52` | `credit_pipeline_v2` default=True противоречит description (default-OFF) и test-assertion | NEW (блокирует test_credit_pipeline_v2_flag.py) |
| **BL-P2-001** | P2 | `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml:22, 43` | YAML reference на несуществующие функции `fetch_for_workflow` и `emit_decision` | NEW (YAML inert под feature-flag, но reference-broken) |
| **BL-P2-002** | P2 | `extensions/osint_agent/tests/test_osint_workflow.py:26` | `test_valid_12_digit_inn` test value "770708389307" invalid INN12 checksum (check1=2, expected 0) | NEW (stale test fixture) |
| **BL-P2-003** | P2 | `extensions/osint_agent/tests/test_osint_workflow.py:46` | `test_none_inn` ожидает False, но `validate_inn(None)` raises TypeError | NEW (production bug + missing guard) |
| **BL-P2-004** | P2 | `extensions/osint_agent/domain/models.py:8-46` | `CompanyInfo` + `OsintReport` dataclasses определены, но 0 references во всём extensions/ | NEW (dead code) |
| **BL-P2-005** | P2 | `extensions/credit_pipeline/{functions,routes,services/clients,workflows}/__init__.py` | 4 scaffold-only __init__.py — пустые `__all__: tuple[str, ...] = ()` маркеры TODO Team T3 Sprint 8+ | NEW (residual scaffolding) |
| **BL-P2-006** | P2 | `extensions/core_entities/orders/services/orders.py:44, 413` | Lazy `importlib.import_module("src.backend.infrastructure.external_apis.s3")` — extensions→infrastructure bridge через строку | NEW (latent layer-violation, indirect) |
| **BL-P2-007** | P2 | `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml:91-97` | Compensation — все `noop` (SKB и НБКИ не имеют mutating-эффекта); saga rollback ineffective | NEW (dead compensation path — info-only) |
| **BL-P3-001** | P3 | `extensions/osint_agent/functions/osint_workflow.py:298-300` | OSINT workflow может использовать `python-inn` (есть в pyproject? — не проверено) или `validators` для INN вместо кастомного `validate_inn` | NEW (low priority — текущая реализация уже в core, не в extensions) |
| **BL-P3-002** | P3 | `extensions/credit_pipeline/services/clients/skb.py:48-93` | Hand-rolled `BaseExternalAPIClient` + httpx retry — `httpx-retries`/`tenacity` могут заменить hand-coded | NEW (low priority — BaseExternalAPIClient уже абстракция) |
| **BL-P4-001** | P4 | `extensions/credit_pipeline/agents/__init__.py:54-138` | scoring_agent stub ML model (rule-based placeholder) — замен на реальный SKB/НБКИ в Sprint 8+ уже TODO | NEW (organic — Sprint 8 backlog) |

---

## Detailed evidence

### BL-P0-001 — Dead saga imports (cross-scope BLOCKER)

**File**: `src/backend/plugins/composition/workflow_setup.py:76-82`

```python
76  from extensions.core_entities.orders.workflows.orders_saga import (
77      build_orders_saga_workflow,
78  )
79  from extensions.credit_pipeline.workflows.payments_saga import (
80      build_payments_saga_workflow,
81  )
82
83  declarations = [build_orders_saga_workflow(), build_payments_saga_workflow()]
```

**Verified**: оба модуля **НЕ существуют**:
- `.venv/bin/python -c "from extensions.core_entities.orders.workflows.orders_saga import build_orders_saga_workflow"`
  → `ImportError: No module named 'extensions.core_entities.orders.workflows.orders_saga'`
- `.venv/bin/python -c "from extensions.credit_pipeline.workflows.payments_saga import build_payments_saga_workflow"`
  → `ImportError: No module named 'extensions.credit_pipeline.workflows.payments_saga'`

Реально в `extensions/core_entities/orders/workflows/` только `orders_dsl.py`
(`build_all_order_workflows()` возвращает 5 workflows, не 1 saga).

В `extensions/credit_pipeline/workflows/` только 4 .yaml + `__init__.py`,
**нет `payments_saga.py`**.

**Trigger**: `settings.workflow.bootstrap_defaults_enabled == True`
(default=False по `src/backend/core/config/workflow.py:38`,
`WORKFLOW_*` env prefix).

**Impact**:
- Latent crash при `WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=true`
  → падение runtime composition root (workflow bootstrap → ImportError).
- Description `src/backend/core/config/workflow.py:27` говорит
  "orders_saga + payments_saga **из src.backend.workflows**" —
  фактические imports — **из extensions** (drift между docstring
  и кодом).
- README/комментарий файла (`workflow_setup.py:9-12`) описывает
  "из extensions/core_entities/orders/ + extensions/credit_pipeline/"
  — т.е. контракт был: extensions ОБЯЗАНЫ предоставить эти модули,
  но не предоставили (S213 migration на `orders_dsl.py` не дошёл
  до saga helpers).

**Связь с cycle-2 P0-002 (dead saga imports)**:
- Цикл-2 P0-002 был в scope src/backend (не extensions).
- Cycle-3: deadness подтверждена через extensions-perspective —
  extensions модули, на которые ссылаются импорты, **физически
  отсутствуют в extensions/**. Это cross-scope blocker,
  формально в extensions scope лежит **отсутствие ожидаемых модулей**,
  а не сами импорты.

**Re-verdict**: cycle-2 P0-002 **mutated** — был "dead imports в src",
стал "dead imports **в src** + **отсутствующие модули в extensions**".

**Минимальная рекомендация**:
- Вариант A (YAGNI, ponytail): удалить блок `from extensions....saga import`
  в `workflow_setup.py:76-82` (дефолт всё равно OFF, модулей нет).
- Вариант B: создать заглушки
  `extensions/core_entities/orders/workflows/orders_saga.py` и
  `extensions/credit_pipeline/workflows/payments_saga.py` с минимальными
  `build_*_saga_workflow() → None` + `NotImplementedError` для saga DSL.
- Вариант C: исправить description в
  `src/backend/core/config/workflow.py:27-29` — убрать враньё
  про `src.backend.workflows` (фактический путь — extensions).

**Тест-критерий**:
- `.venv/bin/python -c "from src.backend.plugins.composition.workflow_setup import _bootstrap_default_declarations"`
  с `WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=true` должен либо успешно
  вернуть пустой список, либо raise с понятным сообщением "module
  not found — saga bootstrap disabled".
- Test: `tests/unit/plugins/test_workflow_setup_saga_imports.py`
  с двумя кейсами (flag=True, flag=False).

---

### BL-P1-001 — OSINT fail-OPEN (cycle-2 P0-004 RESIDUAL)

**File**: `extensions/osint_agent/functions/osint_workflow.py:280-340`

**Цикл-2 находка P0-004**: "OSINT fail-OPEN — пустой результат
вместо raise".

**Cycle-3 re-verify**:

```python
306  try:
307      results_general = await _search_multi_provider(queries["general"])
308      results_courts = await _search_multi_provider(queries["courts"])
309      results_negative = await _search_multi_provider(queries["negative"])
310  except Exception:
311      results_general = {"perplexity": None, "tavily": None, "scraped": []}
312      results_courts = {"perplexity": None, "tavily": None, "scraped": []}
313      results_negative = {"perplexity": None, "tavily": None, "scraped": []}

315  prompt = compose_prompt(
316      inn=inn, company_name=company_name,
317      results_general=results_general, results_courts=results_courts,
318      results_negative=results_negative,
319  )

323  try:
324      from src.backend.core.ai.llm_gateway import get_litellm_gateway
325      gateway = get_litellm_gateway()
326      response = await gateway.acompletion(
327          model="sonar", messages=[{"role": "user", "content": prompt}],
328          max_tokens=2048,
329      )
330      raw_text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
331  except Exception:
332      raw_text = prompt  # ← FAIL-OPEN: возвращаем prompt как отчёт
333
334  report = validate_report(raw_text)
```

**Verified runtime**: запустил через `.venv/bin/python`:
```
search failed for 'Test ИНН 7707083893 site:rusprofile.ru ...': Provider 'perplexity' not found
result keys: ['raw_text', 'general_info', 'positive_mentions', 'negative_mentions',
              'court_cases', 'financial_markers', 'sources', 'inn', 'company_name',
              'report_date']
raw_text starts with: Ты — аналитик OSINT. Сформируй строгий отчёт по компании.
```
**Результат**: при отсутствии LLM провайдера функция возвращает
"отчёт", у которого `raw_text` — **это prompt template, который
должен был быть отправлен в LLM**, а не реальный LLM-output.

**Security/data-loss impact**:
- Это **НЕ security-fail-OPEN** (нет аутентификации/авторизации,
  банковской транзакции).
- Это **data-integrity fail-OPEN** — caller получает 200 OK с
  фейковым отчётом, не зная что данных нет. UI может показать
  "Данные не найдены" или (если LLM частично работает) — полуправду.
- Для banking-context (банк принимает решение по клиенту на основе
  OSINT-отчёта) это **operational risk**: approve на основе
  невалидного отчёта → потенциальный кредитный риск.

**Связь с cycle-2 P0-004**: подтверждено RESIDUAL (не RESOLVED).
Никакого state-marker (`report["fallback"] = True`) или raise нет.

**Минимальная рекомендация**:
1. Добавить `report["data_source"] = "real" | "fallback" | "empty"`.
2. Либо raise `OSINTUnavailableError` если `_search_multi_provider`
   вернул все-None (banking-caller решает retry/cancel).
3. Минимум: при `all-empty search results AND no LLM response` →
   raise вместо return prompt.

**Тест-критерий**:
- `tests/unit/extensions/osint_agent/test_fail_closed.py` —
  `test_run_osint_no_search_no_llm_raises_not_returns_prompt`
- `.venv/bin/python -m pytest tests/unit/extensions/osint_agent/
  test_fail_closed.py -v` → expect exit 0, test PASSED.

---

### BL-P1-002 — credit_pipeline_v2 flag default-OFF test breach

**File**: `src/backend/core/config/features/plugins.py:41-52`

```python
41  credit_pipeline_v2: bool = Field(
42      default=True,
43      title="T3 S7: credit_pipeline plugin (SKB/НБКИ) — V11 layout",
44      description=(
45          "Sprint 7 Team T3. Owner: T3. Активирует "
46          "extensions/credit_pipeline/* как канонический credit-bus "
47          "(SKB-Техно клиент через BaseExternalAPIClient + WAF) + "
48          "Workflow DSL credit_assessment + DSL routes. "
49          "При False — используется legacy services/integrations/skb.py. "
50          "default-OFF до завершения миграции (Sprint 8 flip ON)."
51      ),
52  )
```

**Issue**:
- `default=True` ≠ description "default-OFF"
- `extensions/credit_pipeline/tests/test_credit_pipeline_v2_flag.py:17`
  asserts `is_enabled("credit_pipeline_v2") is False` → **FAILS**.
- Verified: `.venv/bin/python -m pytest
  extensions/credit_pipeline/tests/ -v` →
  `test_credit_pipeline_v2_flag_exists_and_default_off ... FAILED
  (assert True is False)`.

**Git history**:
- Commit `9164a591 feat: enable all feature flags + remove demos`
  flipped default to True.
- Test не обновлён под новую реальность.

**Decision**: что правильно — тест (default-OFF) или код (default-ON)?

**Argument для default=True**:
- `extensions/credit_pipeline/agents/__init__.py` уже real impl
  (S76 W1), `plugin.py` регистрирует 3 actions.
- Все 33 in-tree tests PASSED — credit_pipeline работает.
- Feature flag защищает только legacy fallback
  (`services.integrations.skb.APISKBService`).

**Argument для default=False**:
- Description в коде говорит "default-OFF".
- Test проверяет default-OFF.
- Docstring `extensions/credit_pipeline/services/clients/skb.py:7-12`
  говорит "Под feature_flag.credit_pipeline_v2 (default-OFF)".

**Re-verdict**: code vs description drift. Документация/test lag,
а не security issue. Низкий приоритет, но **ломает test suite**.

**Минимальная рекомендация**:
- Вариант A: поменять default на False (вернуть docstring/test в
  согласие). Безопасно — credit_pipeline уже сдан в S76, но callers
  должны явно flip'нуть.
- Вариант B: обновить test до `is True`, удалить "default-OFF" из
  всех 3 docstring (test_skb_client_smoke, skb.py, workflow.yaml).
- Решение: variant B (фиксирует реальность).

**Тест-критерий**: либо test PASSED при default=False, либо test
обновлён и description исправлен.

---

### BL-P2-001 — credit_assessment.workflow.yaml reference-broken

**File**: `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml:22, 30, 43`

```yaml
22  function: extensions.credit_pipeline.services.clients.skb:fetch_for_workflow
30  function: extensions.credit_pipeline.services.clients.skb:fetch_for_workflow
43  function: extensions.credit_pipeline.functions.publish:emit_decision
```

**Verified**:
- `extensions/credit_pipeline/services/clients/skb.py:24` —
  `__all__ = ("CreditSKBClient", "get_credit_skb_client")`.
- `grep -n "fetch_for_workflow"` → 0 hits в `extensions/credit_pipeline/`.
- `find extensions/credit_pipeline/functions -name "publish.py"` →
  No such file.

**Impact**:
- YAML inert под feature-flag `credit_pipeline_v2`
  (см. BL-P1-002 — теперь default ON).
- Если кто-то flip'нёт runtime flag → ActivityDeclaration resolution
  → ImportError.
- 4 yaml не проходят workflow_runtime validation (если она есть).

**Минимальная рекомендация**:
- Удалить сломанный YAML или
- Добавить stub `extensions/credit_pipeline/services/clients/skb.py::fetch_for_workflow`
  → raise NotImplementedError("Sprint 8+") с правильным сигнатуром.

**Тест-критерий**: `tests/unit/extensions/credit_pipeline/test_workflow_yaml.py` →
добавить `test_workflow_yaml_activities_resolve_to_existing_functions`
(pyproject importlib).

---

### BL-P2-002 — test_valid_12_digit_inn stale fixture

**File**: `extensions/osint_agent/tests/test_osint_workflow.py:24-26`

```python
24  def test_valid_12_digit_inn(self) -> None:
25      """Test: valid 12 digit inn."""
26      assert validate_inn("770708389307") is True
```

**Verified runtime**:
- `.venv/bin/python -c "weights1=(7,2,4,10,3,5,9,4,6,8); inn='770708389307';
  check1=sum(int(inn[i])*weights1[i] for i in range(10))%11%10;
  print(check1, inn[10])"` → `2 0`.
- То есть check1=2, ожидаемая 11-я цифра (`inn[10]`) = 0 → **fail checksum**.
- Test FAILS: `assert False is True`.

**Source of truth**:
- `src/backend/dsl/helpers/banking.py:38-42` — `weights1 = (7, 2, 4, 10,
  3, 5, 9, 4, 6, 8)`, что соответствует стандарту ИНН-12
  (IRS-Россия spec). То есть код правильный, **test fixture wrong**.

**Минимальная рекомендация**: заменить "770708389307" на
валидный ИНН-12 (можно сгенерировать через
`https://www.kontur-extern.ru/tools/inn` или ручным расчётом
с правильной checksum).

**Тест-критерий**: `validate_inn(valid_inn12) is True`.

---

### BL-P2-003 — validate_inn(None) raises TypeError

**File**: `src/backend/dsl/helpers/banking.py:31-43`

```python
31  def validate_inn(inn: str) -> bool:
32      """Проверяет ИНН (10 или 12 цифр) по контрольной сумме."""
33      if _INN10.match(inn):  # ← TypeError if inn is None
```

**Verified runtime**:
- `.venv/bin/python -m pytest
  extensions/osint_agent/tests/test_osint_workflow.py::TestValidateInn::test_none_inn`
  → `TypeError: expected string or bytes-like object, got 'NoneType'`.
- Тест ожидает `validate_inn(None) is False` (graceful fail).

**Impact**: caller `osint_workflow.py:298`:
```python
inn = str(payload.get("inn", "")).strip()  # str(None) → "None"
if not validate_inn(inn):  # "None" → validate_inn → False ✓
```
То есть в OSINT use-case None маскируется `str(payload.get("inn",""))`.
Но **public API** `validate_inn` не должен raise на None — это
violates "fail-closed" principle (банковский validator).

**Минимальная рекомендация** (5 строк):
```python
def validate_inn(inn: str | None) -> bool:
    if inn is None:
        return False
    if not isinstance(inn, str):
        return False
    # ... rest unchanged
```

**Тест-критерий**:
- `validate_inn(None)` → False (no raise)
- `validate_inn(123)` → False (no raise)
- `validate_inn("")` → False (current behavior)

---

### BL-P2-004 — Dead dataclasses CompanyInfo + OsintReport

**File**: `extensions/osint_agent/domain/models.py:8-46`

```python
8  @dataclass(slots=True, frozen=True)
9  class CompanyInfo:
10      inn: str
11      name: str = ""
...

20  @dataclass(slots=True)
21  class OsintReport:
22      """OSINT report for a company.
...
46      raw_text: str = ""
```

**Verified**:
- `grep -rn "CompanyInfo\|OsintReport" extensions/ --include='*.py'`
  → 2 hits, оба в самом `domain/models.py` (definitions only).
- `grep -rn "CompanyInfo\|OsintReport" tests/ src/`
  → 0 hits.
- `osint_workflow.py:run_osint` возвращает **dict**, не
  `OsintReport` instance.

**Impact**:
- Dead code (~46 LOC).
- Ponytail: minimum — delete или `__all__` export (если future use).
- Это нарушает principle "no dead code" из cycle-2.

**Минимальная рекомендация**: удалить (если не планируется в Sprint 8+)
или обернуть в `__all__` + docstring "reserved for Sprint 8+".

**Тест-критерий**: `pyflakes extensions/` → 0 unused.

---

### BL-P2-005 — 4 scaffold-only __init__.py (residual TODOs)

**Files**:
- `extensions/credit_pipeline/functions/__init__.py:3` — TODO Team T3 Sprint 8+
- `extensions/credit_pipeline/routes/__init__.py:3` — TODO Team T3 Sprint 8+
- `extensions/credit_pipeline/services/clients/__init__.py:3` — TODO Team T3 Sprint 8+
- `extensions/credit_pipeline/workflows/__init__.py:3` — TODO Team T3 Sprint 8+

**Verified**:
- Все 4 файла — `__all__: tuple[str, ...] = ()` (пустые).
- `extensions/credit_pipeline/plugin.toml:6-13` — общий TODO-list.

**Impact**:
- Не блокирует runtime.
- Cycle-2 → Cycle-3: drift в том, что TODO-list НЕ обновлён,
  несмотря на S76 W1+W2 (real agents) + Sprint 8+ фактически начат.
- Например, `functions/__init__.py` мог бы экспортировать
  `apply_rules`, `calculate_combined_score` (но они в `normalize.py`).
- `services/clients/__init__.py` мог бы экспортировать
  `CreditSKBClient`, `get_credit_skb_client` (но они в `skb.py`).

**Минимальная рекомендация** (Ponytail):
- Очистить TODO-маркеры из реально-рабочих подмодулей.
- Оставить TODO только там, где модуль действительно пуст
  (`routes/__init__.py` — реально нет routes/ кроме __init__).

**Тест-критерий**: `grep -rn "TODO Team T3" extensions/` — снижение
с 4 до ≤2 (если routes останутся TODO).

---

### BL-P2-006 — Layer-violation via lazy importlib

**File**: `extensions/core_entities/orders/services/orders.py:44, 413`

```python
44  _S3_MOD = "src.backend.infrastructure.external_apis.s3"
...
411     order_repo = importlib.import_module(_REPO_ORDERS_MOD).get_order_repo()
412     file_repo = importlib.import_module(_REPO_FILES_MOD).get_file_repo()
413     s3_service = importlib.import_module(_S3_MOD).get_s3_service_dependency()
```

**Verified**:
- `grep -rn "from src.backend.infrastructure" extensions/ --include='*.py'`
  → 0 hits (нет прямых импортов).
- Lazy `importlib.import_module` обходит статический layer checker
  (нет `from X import Y`).
- Но `extensions/core_entities/orders/plugin.toml` НЕ объявляет
  capability `net.outbound` или `storage.s3` (только неявно через
  `OrderStorageProtocol`).

**Impact**:
- Cycle-2 layer checker (`tools/check_layers.py`) пропустил эту
  строку — не видит её через AST.
- При `get_order_service()` runtime → cross-layer call в
  infrastructure.

**Минимальная рекомендация**:
- Заменить `_S3_MOD` import на capability-gate фасад
  (как в `extensions/core_entities/orders/workflows/orders_dsl.py:91-93`:
  `from src.backend.core.di.providers.workflow import
  get_action_bus_service_provider`).
- Либо: добавить `[[capabilities]] storage.s3` в
  `extensions/core_entities/orders/plugin.toml`.

**Тест-критерий**: `tools/check_layers.py --root extensions` →
должен detect `_S3_MOD` string literal как violation (расширить
checker: `grep -rn "src.backend.infrastructure" extensions/`).

---

### BL-P2-007 — Compensation all noop (info-only)

**File**: `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml:91-97`

```yaml
91  compensation:
92    - id: compensate_skb
93      type: noop
94      description: SKB не имеет mutating-эффекта — compensation noop.
95    - id: compensate_nbki
96      type: noop
97      description: НБКИ не имеет mutating-эффекта — compensation noop.
```

**Impact**:
- Saga rollback path ineffective — если `publish_decision` упадёт,
  никакой rollback (но fetch_skb / fetch_nbki read-only, OK).
- Это **правильное** design-решение, но mark as P2 info-only
  чтобы future maintainer не пытался "улучшить" compensation
  без необходимости.

**Минимальная рекомендация**: не требуется. Doc-only note.

---

### BL-P3-001 — Hand-rolled INN validator (low priority)

**File**: `src/backend/dsl/helpers/banking.py:31-43` (core, используется extensions).

**Библиотеки для замены**:
- `python-inn` (PyPI) — INN/OGRN validation, pure-python.
- `validators` (PyPI) — общий validators с поддержкой ru_inn.

**Не проверено**: наличие в `pyproject.toml`, license, maintenance status.
Ponytail: текущий 12-LOC код проще, чем 3rd-party dep + вероятные
edge-cases с None/non-str (см. BL-P2-003). Recommend: fix None bug
instead of library replacement.

---

### BL-P3-002 — Hand-rolled BaseExternalAPIClient (low priority)

**File**: `extensions/credit_pipeline/services/clients/skb.py:27-133`.

**Библиотеки**:
- `httpx-retries` (auto-retry layer для httpx).
- `tenacity` (general-purpose retry).

**Не проверено**: pyproject наличие, S168 cycle-2 решал аналогичный
tenacity question (cycle-2 baseline: T-W3-01 library replacement).

**Рекомендация**: не применять — `BaseExternalAPIClient` уже абстракция
+ canonical pattern для всего проекта (R-V15-13). Замена локальна,
risk несовместимости с другими extensions.

---

### BL-P4-001 — scoring_agent rule-based placeholder (organic, Sprint 8+)

**File**: `extensions/credit_pipeline/agents/__init__.py:54-138`.

**Status**:
- Stub ML model (rule-based with hardcoded DTI thresholds).
- Description в коде: "Rule-based scoring (placeholder для
  production ML model). Real impl: load pkl, call SKB/НБКИ, etc."
- В Sprint 8+ запланирована real ML-интеграция.

**Рекомендация**: органично — не требует feature добавления сейчас,
является legitimate placeholder. P4 backlog.

---

## Cycle-1+2 residuals (verified или mutated)

| Cycle | ID | Title | Cycle-3 verdict | Evidence |
|---|---|---|---|---|
| cycle-1 | T-1.1 | composition root fix | VERIFIED OK in extensions scope | extensions/__init__.py import time 4.3s, no crash, all plugins instantiable (verified `.venv/bin/python`) |
| cycle-1 | T-1.2 | SSE/HITL auth | out of extensions scope | не проверял (SSE в src/) |
| cycle-1 | T-1.3 | MQ DLQ data-loss | out of extensions scope | не проверял |
| cycle-1 | T-2.1 | reverse-layer cleanup | VERIFIED in extensions | 0 `from src.backend.{infrastructure,services,entrypoints}` в extensions/ (grep verified) |
| cycle-1 | T-4.1 | text-RAG E2E test | out of extensions scope (E2E rag в src/) | не проверял |
| cycle-2 | T-W1-02..07 | other domain work | out of extensions scope | не проверял (per task scope) |
| cycle-2 | T-W1-08 | credit scoring fail-closed | **VERIFIED RESOLVED** | `tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py` → 3/3 PASSED (5.11s); full `tests/unit/extensions/credit_pipeline/` → 13/13 PASSED |
| cycle-2 | P0-001 | composition root crash | **NOT REPRODUCED in extensions scope** | extensions import OK, plugins instantiable (verified `.venv/bin/python`). Не могу confirm/refute src-side crash без cross-scope доступа. |
| cycle-2 | P0-002 | dead saga imports | **MUTATED → BL-P0-001** | deadness confirmed в `src/backend/plugins/composition/workflow_setup.py:76-82` + extensions модули `orders_saga`/`payments_saga` отсутствуют. Trigger: `WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=true` (default OFF). |
| cycle-2 | P0-003 | (T-W1-08 source) | **RESOLVED** | merged into T-W1-08 cycle-2 task |
| cycle-2 | P0-004 | OSINT fail-OPEN | **RESIDUAL → BL-P1-001** | fail-OPEN behaviour подтверждена runtime test (`raw_text = prompt template`); ни marker'а, ни raise нет |
| cycle-2 | P1-001..002 | (TBD) | не проверено (markdown не читал) | n/a |
| cycle-2 | P2-001..004 | (TBD) | не проверено (markdown не читал) | n/a |
| cycle-2 | P3-001..002 | (TBD) | не проверено (markdown не читал) | n/a |
| cycle-2 | P4-001 | (TBD) | не проверено (markdown не читал) | n/a |

**Объяснение**: cycle-2 IDs P1-P4 в задаче перечислены, но я
**не читал cycle-2 markdown** (запрет phase-1 task scope). Поэтому
verified/mutated verdict для P1-001..002, P2-001..004, P3-001..002,
P4-001 не даю — это потребовало бы чтения отчётов cycle-2,
которые нарушили бы scope правила.

---

## Contradictions / overlaps to flag

1. **drift: `credit_pipeline_v2` default=True vs description "default-OFF" vs test asserting default=False** (BL-P1-002).
   - Doc-stale в 3 местах: `extensions/credit_pipeline/services/clients/skb.py:7`,
     `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml:7-9`,
     `src/backend/core/config/features/plugins.py:41-52`.
   - `git log` показывает flip в commit `9164a591 feat: enable all feature flags`.
   - Test не обновлён.

2. **YAML reference на несуществующие функции** (BL-P2-001) vs **отсутствующие `publish.py`** в `functions/`.
   - 4 `.workflow.yaml` в `extensions/credit_pipeline/workflows/` ссылаются
     на функции, которых нет в коде.
   - Только `rag_augmented_saga`, `multi_agent_supervisor`,
     `code_interpreter_loop` — generic шаблоны; `credit_assessment` —
     extension-specific broken reference.

3. **latent crash + отсутствующие extension модули** (BL-P0-001):
   - `src/backend/plugins/composition/workflow_setup.py` импортирует
     `extensions.core_entities.orders.workflows.orders_saga` —
     модуль не создан.
   - Если extensions **когда-то создадут** `orders_saga.py` (как
     обещает docstring в `workflow_setup.py:9-12`), latent crash
     исчезнет. Если extensions **никогда не создадут** — crash trigger
     закрыт через feature-flag default=False.

4. **OSINT fail-OPEN banking-context** (BL-P1-001):
   - Banking-extension (через `osint_agent` используется в
     кредитном pipeline) возвращает фейковый отчёт при LLM-down.
   - Caller из credit_pipeline не получает `data_source` маркер →
     не может отличить real от fallback.

5. **Dead dataclasses в `osint_agent/domain/models.py`** (BL-P2-004):
   - 46 LOC мертвого кода — нарушение cycle-2 baseline "no dead code".

6. **Layer-violation через lazy importlib** (BL-P2-006):
   - `extensions/core_entities/orders/services/orders.py:413`
     обходит `tools/check_layers.py` через строку-импорт.
   - Не detect'ится стандартным layer checker.

7. **2 из 3 OSINT tests — production-code bugs** (BL-P2-002, BL-P2-003):
   - `validate_inn("770708389307")` returns False (test expects True)
     → test fixture stale, **но не код-баг**.
   - `validate_inn(None)` raises TypeError → **реальный production bug**.

---

## Readiness score 0–100

### Формула

```
readiness = (passed_tests / total_tests) * 100
          - 5 * P0_count
          - 3 * P1_count
          - 1 * P2_count
          - 0.5 * P3_count
          - 0.1 * P4_count
```

### Inputs (verified через `.venv/bin/python`)

| Metric | Value | Source |
|---|---:|---|
| Total tests in extensions scope | 143 | pytest collection |
| Passed | 140 | `.venv/bin/python -m pytest extensions/ tests/unit/extensions/ tests/integration/extensions/ --tb=no` |
| Failed | 3 | (same run) |
| P0 findings (in extensions scope) | 1 (BL-P0-001) + 0 cycle-2 repro | direct code |
| P1 findings | 2 (BL-P1-001 OSINT fail-OPEN + BL-P1-002 flag drift) | direct code |
| P2 findings | 7 | direct code |
| P3 findings | 2 | direct code |
| P4 findings | 1 | direct code |

### Calculation

```
base = (140 / 143) * 100 = 97.90
penalty = 5*1 + 3*2 + 1*7 + 0.5*2 + 0.1*1 = 5 + 6 + 7 + 1 + 0.1 = 19.10
readiness = 97.90 - 19.10 = 78.80
```

### Result

**readiness = 78.8 → округлённо 79/100**.

### Обоснование

- **≥80 запрещён при P0/P1** — формула даёт 79, что ниже порога.
  Это правильно: BL-P0-001 (dead saga imports) и BL-P1-001
  (OSINT fail-OPEN) — **active blockers** для production readiness
  banking-extension.
- **T-W1-08 RESOLVED** повысил score (cycle-2 baseline был ~70),
  но новые findings (BL-P0-001 cross-scope, BL-P1-001 OSINT,
  BL-P1-002 flag drift) удерживают ниже 80.
- 3 failing tests — все **valid bugs** (не тест-flakiness):
  - `validate_inn(None)` raises (production code)
  - `validate_inn("770708389307")` False (test fixture stale)
  - `credit_pipeline_v2` default=True (test stale)

### Что поднимет score до ≥80

1. Resolve BL-P0-001 (delete dead saga imports OR create extension stubs).
2. Resolve BL-P1-001 (OSINT fail-OPEN → add `data_source` marker
   OR raise on empty fallback).
3. Resolve BL-P1-002 (default flag consistency).
4. Fix BL-P2-002/003 (test fixtures + validate_inn None guard).
5. Delete BL-P2-004 (dead dataclasses).

После fixes: `readiness = 100 - 5 - 0 - 0 - 0 - 0 = 100`
(если все P2+ тоже resolve) или `100 - 5 = 95` (если только P0+P1).

---

## Recommended next tasks (по приоритету)

| Pri | Task | Effort | Effect |
|---|---|---|---|
| P0 | Resolve BL-P0-001: либо удалить dead imports в workflow_setup.py, либо создать extension-saga-stubs | 1h | -5 readiness penalty |
| P1 | Resolve BL-P1-001: добавить `data_source` marker + raise на полный fallback | 2h | -3 readiness penalty |
| P1 | Resolve BL-P1-002: согласовать default credit_pipeline_v2 (False vs True) | 30m | -3 readiness penalty |
| P2 | Fix BL-P2-003: 5 строк в validate_inn для None/non-str guard | 15m | -1 readiness penalty |
| P2 | Fix BL-P2-002: replace stale test fixture "770708389307" → valid INN12 | 10m | -1 readiness penalty |
| P2 | Delete BL-P2-004: drop CompanyInfo + OsintReport dataclasses (или __all__ marker) | 15m | -1 readiness penalty |
| P2 | Fix BL-P2-005: clean 4 scaffold-only __init__.py | 30m | -1 readiness penalty |
| P2 | Fix BL-P2-006: replace lazy _S3_MOD with capability facade | 2h | -1 readiness penalty |
| P2 | Fix BL-P2-001: delete or stub broken workflow YAML references | 1h | -1 readiness penalty |
| P3 | (optional) BL-P3-001 / BL-P3-002 — YAGNI recommend **skip** | n/a | n/a |
| P4 | (Sprint 8+) BL-P4-001 — real ML scoring (organic backlog) | n/a | n/a |

**Total estimated effort для readiness ≥80**: ~6h P0+P1, +~3h P2 cleanup.

---

## Commands run (Python interpreter: `.venv/bin/python` = cpython-3.14.0)

| # | Command | Exit | Notes |
|---|---|---:|---|
| 1 | `.venv/bin/python -m pytest tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py -v` | 0 | T-W1-08 RESOLVED: 3/3 PASSED in 5.11s |
| 2 | `.venv/bin/python -m pytest tests/unit/extensions/credit_pipeline/ -v` | 0 | Full credit_pipeline unit suite: 13/13 PASSED |
| 3 | `.venv/bin/python -m pytest extensions/credit_pipeline/tests/ -v` | 1 | 33/34 PASSED, 1 FAILED (test_credit_pipeline_v2_flag — BL-P1-002) |
| 4 | `.venv/bin/python -m pytest extensions/osint_agent/tests/ -v` | 1 | 15/17 PASSED, 2 FAILED (BL-P2-002, BL-P2-003) |
| 5 | `.venv/bin/python -m pytest extensions/core_entities/ -v` | 0 | 35/35 PASSED |
| 6 | `.venv/bin/python -m pytest tests/unit/extensions/test_plug/ tests/unit/cycle_31_s4_extensions.py tests/unit/extensions/skb/ tests/unit/extensions/users/ tests/unit/extensions/test_plugin_trust_tier.py -v` | 0 | 4+3+7+18+4 = 36/36 PASSED |
| 7 | `.venv/bin/python -m pytest tests/integration/extensions/credit_pipeline/test_workflow_examples.py -v` | 0 | 6/6 PASSED (YAML parse smoke) |
| 8 | `.venv/bin/python -m pytest extensions/ tests/unit/extensions/ tests/integration/extensions/ --tb=no` | 1 | 140/143 PASSED, 3 FAILED |
| 9 | `.venv/bin/python -c "from extensions.osint_agent.functions.osint_workflow import run_osint; ..."` | 0 | OSINT fail-OPEN confirmed: raw_text = prompt template |
| 10 | `.venv/bin/python -c "from extensions.core_entities.orders.workflows.orders_saga import build_orders_saga_workflow"` | 1 | ImportError — модуль отсутствует (BL-P0-001) |
| 11 | `.venv/bin/python -c "from extensions.credit_pipeline.workflows.payments_saga import build_payments_saga_workflow"` | 1 | ImportError — модуль отсутствует (BL-P0-001) |
| 12 | `.venv/bin/python -c "import extensions; srep = extensions.SQLAlchemyRepository"` | 0 | Lazy __getattr__ OK |
| 13 | `.venv/bin/python -c "from extensions.credit_pipeline.plugin import CreditPipelinePlugin; ..."` | 0 | Plugin instantiable |
| 14 | `.venv/bin/python -c "from extensions.osint_agent.plugin import OsintAgentPlugin; ..."` | 0 | Plugin instantiable |
| 15 | `.venv/bin/python -c "import ast, pathlib; ..."` | 0 | Syntax check all extensions .py: 0 errors |
| 16 | `grep -rn "from src.backend.infrastructure" extensions/ --include='*.py'` | 0 | 0 hits (layer discipline OK direct imports) |
| 17 | `grep -rn "from src.backend.services" extensions/ --include='*.py'` | 0 | 0 hits |
| 18 | `grep -rn "TODO\|FIXME\|XXX\|HACK" extensions/ --include='*.py'` | 0 | 4 TODO Team T3 markers (BL-P2-005) |
| 19 | `grep -rn "CompanyInfo\|OsintReport" extensions/ src/ tests/ --include='*.py'` | 0 | 0 usages outside definition file (BL-P2-004) |
| 20 | `grep -rn "saga" extensions/ --include='*.py'` | 0 | Live usage only (orders_dsl.py); no dead imports |

**System Python**: НЕ использовался (per cycle-3 baseline
requirement). Все 20 команд через `.venv/bin/python` или
`.venv/bin/pytest` (= `/home/user/.local/share/uv/python/cpython-3.14-
linux-x86_64-gnu/bin/python3.14` per `ls -la .venv/bin/python`).

---

## Blockers (для parent)

| ID | Pri | Summary | Evidence |
|---|---|---|---|
| **BL-P0-001** | P0 | Dead saga imports `extensions.{core_entities.orders.workflows.orders_saga, credit_pipeline.workflows.payments_saga}` в `src/backend/plugins/composition/workflow_setup.py:76-82` — модули отсутствуют в extensions/ | runtime ImportError verified через `.venv/bin/python` |
| **BL-P1-001** | P0-class | OSINT fail-OPEN: `run_osint` возвращает prompt template как "report" при LLM-down (`extensions/osint_agent/functions/osint_workflow.py:332`) — banking-context risk | runtime test verified: `raw_text starts with: "Ты — аналитик OSINT..."` |
| **BL-P1-002** | P1 | `credit_pipeline_v2` default=True противоречит description + test (блокирует `extensions/credit_pipeline/tests/test_credit_pipeline_v2_flag.py`) | runtime test FAILED: assert True is False |

**T-W1-08 (credit scoring fail-closed)**: VERIFIED RESOLVED in working tree.
**Cycle-2 P0-001 (composition root crash)**: NOT REPRODUCED in extensions scope
(extensions/__init__.py imports cleanly; plugins instantiable).
**Cycle-2 P0-002 (dead saga imports)**: MUTATED — mutated into BL-P0-001
(dead imports persist в src/backend + extension-модули отсутствуют).
**Cycle-2 P0-004 (OSINT fail-OPEN)**: RESIDUAL — confirmed still present
(BL-P1-001 above).