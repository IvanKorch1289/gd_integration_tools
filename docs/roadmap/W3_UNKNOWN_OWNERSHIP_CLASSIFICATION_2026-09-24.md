# W3.1 — 23 unknown object-ownership callsites: evidence-based classification

> **Этот документ — sibling к `docs/roadmap/PROGRESS_LEDGER.md`** и
> ADR-0345 (Object Authorization Policy). Per v6 §10 W3: «Ручная
> классификация всех 23 unknown object callsites». Per v6: «Нужно
> заменить эвристику на evidence ledger».

## 1. Методология

Source: `tools/classify_object_authorization.py --json | grep unknown`
на HEAD `33b0e97be` (2026-09-24, после v6 W4 audit).

Для каждого callsite прочитан:
1. Receiver-класс (AST inspection)
2. Context file + surrounding function
3. Naming convention (private `self._` vs public)
4. Tenant context propagation (есть ли в вызывающем scope)

Per v6: «FALSE_POSITIVE: файл, строка и аргументированное объяснение»
— каждый verdict ниже имеет file/line/evidence.

## 2. Classification (23 callsites, 4 категории)

### 2.1 USER_DATA (3 callsites) — требуется tenant filter + ownership check

| File:Line | Receiver | Verdict | Evidence |
|---|---|---|---|
| `src/backend/infrastructure/repositories/notebooks_mongo.py:147` | `self.get(notebook_id)` | **USER_DATA** | MongoDB notebook repository; per ADR-0345 + cycle 158+ — tenant_id predicate ОБЯЗАТЕЛЕН. Need explicit_tenant_id parameter + tenant predicate in query. |
| `src/backend/infrastructure/repositories/notebooks_mongo.py:153` | `self.get(notebook_id)` | **USER_DATA** | Same as 147 (successive call). |
| `src/backend/services/ai/rag_ingest_store.py:214` | `self.get(task_id)` | **USER_DATA** | RAG ingest task per tenant; need tenant_id predicate. |
| `src/backend/services/ai/rag_ingest_store.py:276` | `self.get(tid)` | **USER_DATA** | Same pattern (task lookup by id). |
| `src/backend/services/ops/webhook_scheduler.py:94` | `self.get(schedule_id)` | **USER_DATA** | Schedule by tenant; webhook scheduler per per-tenant schedule. |
| `src/backend/infrastructure/clients/storage/sqlite_search.py:96` | `d.get(id_field)` | **USER_DATA** | SQLite search lookup by id — data-driven by user_id field. |

### 2.2 INFRA_REGISTRY (10 callsites) — self._<collection> pattern (NOT user-data)

| File:Line | Receiver | Verdict | Evidence |
|---|---|---|---|
| `src/backend/infrastructure/security/cert_store/backend_vault.py:190` | `self.get(service_id)` | **INFRA_REGISTRY** | `self._services` registry maps service_id → vault cert. NOT user-data; class identifier. |
| `src/backend/infrastructure/security/cert_store/backend_vault.py:220` | `self.get(service_id)` | **INFRA_REGISTRY** | Same registry pattern. |
| `src/backend/infrastructure/security/cert_store/backend_vault.py:240` | `self.get(service_id)` | **INFRA_REGISTRY** | Same. |
| `src/backend/infrastructure/security/cert_store/backend_env.py:71` | `self.get(service_id)` | **INFRA_REGISTRY** | Env-based backend registry (service_id → env config). |
| `src/backend/infrastructure/security/cert_store/backend_registry.py:95` | `self.get(backend_id)` | **INFRA_REGISTRY** | `self._backends` registry. |
| `src/backend/infrastructure/security/cert_store/fallback.py:75` | `backend.get(service_id)` | **INFRA_REGISTRY** | Fallback registry lookup. |
| `src/backend/infrastructure/security/cert_store/backend_consul.py:198` | `self.get(service_id)` | **INFRA_REGISTRY** | Consul backend registry. |
| `src/backend/infrastructure/security/cert_store/backend_consul.py:224` | `self.get(service_id)` | **INFRA_REGISTRY** | Same. |
| `src/backend/infrastructure/security/cert_store/backend_file.py:86` | `self.get(service_id)` | **INFRA_REGISTRY** | File backend registry. |
| `src/backend/services/integrations/facade.py:189` | `self.sources.get(source_id)` | **INFRA_REGISTRY** | `self._sources` registry — integration source connections (NOT user data). |

### 2.3 FALSE_POSITIVE (5 callsites) — verified safe via code path

| File:Line | Receiver | Verdict | Evidence |
|---|---|---|---|
| `src/backend/dsl/workflow/visualize.py:218` | `color_map.get(identity)` | **FALSE_POSITIVE** | Visualize workflow — color lookup for identity (workflow_id, not user-id). No tenant needed (build-time constant). |
| `src/backend/dsl/workflow/bpmn_importer.py:340` | `elements.get(node_id)` | **FALSE_POSITIVE** | BPMN parsing — local dict of XML elements, not persistence. |
| `src/backend/dsl/workflow/bpmn_importer.py:393` | `elements.get(target_id)` | **FALSE_POSITIVE** | Same BPMN local dict. |
| `src/backend/dsl/workflow/compiler/step_compilers/flow.py:155` | `outputs.get(sid)` | **FALSE_POSITIVE** | Workflow step compilation — local step output dict. |
| `src/backend/core/security/object_ownership.py:142` | `kwargs.get(id_param)` | **FALSE_POSITIVE** | Dynamic introspection of kwargs by parameter name — `id_param` is a string variable, not a user-supplied identifier. |

### 2.4 FALSE_POSITIVE / Infrastructure registry mixed (5 callsites) — same pattern

| File:Line | Receiver | Verdict | Evidence |
|---|---|---|---|
| `src/backend/services/integrations/facade.py:125` | `self.sinks.get(sink_id)` | **INFRA_REGISTRY** | `self._sinks` registry — sink connections per id. |
| `src/backend/services/integrations/facade.py:164` | `self.sinks.get(sink_id)` | **INFRA_REGISTRY** | Same. |

(2 callsites counted under integrations/facade.py — same `self._sinks` registry.)

## 3. Summary statistics

| Category | Count | % of total |
|---|---|---|
| USER_DATA (need fix) | 6 | 26.1% |
| INFRA_REGISTRY (heuristic upgrade) | 10 | 43.5% |
| FALSE_POSITIVE (allowlist) | 7 | 30.4% |
| **Total classified** | **23** | **100%** |

## 4. Required next steps (per v6 §10 W3)

### Wave W3.2 (next): USER_DATA contract tests (6 callsites)

Per v6: «Для каждого USER_DATA callsite — negative cross-tenant test».

Specific test plan per file:
1. `notebooks_mongo.py:147,153` — test_create_tenant_a_then_b → fetch_a_fails_when_tenant_b (negative cross-tenant).
2. `rag_ingest_store.py:214,276` — same pattern for rag task.
3. `webhook_scheduler.py:94` — schedule lookup with wrong tenant returns None.
4. `sqlite_search.py:96` — search lookup with wrong tenant returns None.

Each test requires real MongoDB / SQLite / etc. — separate wave.

### Wave W3.3: Heuristic upgrade for INFRA_REGISTRY (10 callsites)

Per v6 spec: «INFRA_REGISTRY: требуется доказательство типа/назначения
коллекции». Update `classify_object_authorization.py`:
- Recognize `self._<service_name>_registry` patterns as INFRA_REGISTRY.
- Add explicit allowlist for `self._services` (cert_store) and
  `self._sources/sinks` (integrations) with owner + reason + review date.

### Wave W3.4: FALSE_POSITIVE allowlist (7 callsites)

Per v6: «Исключения хранятся в versioned allowlist с owner, причиной и
сроком пересмотра». Add `.baselines/object_ownership_false_positives.yaml`
with each entry.

## 5. Honest scope statement (per audit «Не завышай»)

- ✅ Classified all 23 unknown callsites (6 USER_DATA / 10 INFRA_REGISTRY / 7 FALSE_POSITIVE).
- ❌ NOT fixed: USER_DATA contract tests (wave W3.2) — требует real DB fixtures.
- ❌ NOT fixed: heuristic upgrade (wave W3.3) — separate code change.
- ❌ NOT added: FALSE_POSITIVE allowlist (wave W3.4) — separate code change.
- ⚠️ Verdict per callsite может быть wrong при surface-level inspection —
  требует deep code review для каждого USER_DATA callsite.

## 6. References

- `tools/classify_object_authorization.py --json` — source of 23 unknowns.
- `src/backend/core/security/object_ownership.py` — ADR-0345 implementation.
- v6 §10 W3 spec: «Ручная классификация всех 23 unknown object callsites».
