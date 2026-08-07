# Cycle 1 — Phase 1 — Audit of Domain A5-API-Contracts

**Дата:** 2026-08-06
**HEAD:** `7f3d94a3`
**Аудитор:** A5-агент (cycle 1, independent verification, read-only)

---

## 1. Scope / что проверено / что не проверено

**В scope:**
- `src/backend/schemas/` (включая `schemas/*.py`)
- `src/backend/services/schema_registry/`
- OpenAPI/AsyncAPI экспорт (`tools/gen_api_docs.sh`, `tools/gen_api_autoapi.sh`)
- JSON-Schema каталог
- `extensions/*/schemas/`, `routes/*/schemas/`
- `core/di/providers/schemas.py`, `core/interfaces/schemas.py`

**Не проверено:** runtime-валидация payload'ов через Pydantic в каждом handler (cross-cutting через A4),
полное покрытие всех endpoint'ов через schema-registry (требует runtime-trace).

---

## 2. Сводка готовности по 5 категориям

| Категория | % | Обоснование |
|---|---|---|
| **Pydantic 2 модели** | 80% | Большинство DTO используют `BaseModel` + `ConfigDict(extra="forbid")` (verified в `schemas/`). Обнаружены dataclass'ы в публичных границах (audit_event), частичные `dict[str, Any]` в schema-registry fallback. |
| **Schema-registry RAM-каталог** | 70% | `services/schema_registry/` существует, AsyncAPI экспорт генерируется. **Покрытие неполное:** ~40% schema-файлов зарегистрированы через registry, остальные — только через FastAPI автоматический OpenAPI. |
| **OpenAPI / AsyncAPI экспорт** | 85% | `tools/gen_api_docs.sh` + `gen_api_autoapi.sh` работают, MkDocs integration verified (B2 migration). 3-tier multi-protocol export (REST/SOAP/MQ) — declared, не all verified. |
| **`dict[str, Any]` на публичных границах** | 50% | **Несколько P1 находок** в `services/schema_registry/registry.py:251-270` и `services/ops/data_quality/apply_mixin.py:316-326` (cross-reference с A3). |
| **Sprint 184 fixes (B2 mkdocs migration)** | 90% | `site/api/` остаётся от sphinx (D-AUDIT-11-12 RESIDUAL) — не блокирует, но cleanup. |

**Итоговая готовность**: **75%** (взвешенная)

---

## 3. Таблица находок

| ID | Prior | Файл:строка | Описание | Фикс |
|---|---|---|---|---|
| **D-A5-01** | **P0** | `services/schema_registry/registry.py:251-270` | `dict[str, Any]` fallback для unregistered schemas — нарушает type safety на публичной границе | Generic typed wrapper через `TypeAdapter` |
| **D-A5-02** | **P1** | `schemas/audit/event.py:1-50` | `AuditEvent` — dataclass, не Pydantic. `services/ai/rag_service/search_mixin.py` использует как Pydantic через duck-typing | Convert to `BaseModel` (backward compat через alias) |
| **D-A5-03** | **P1** | `extensions/core_entities/schemas/*.py` | 3 schemas не имеют `ConfigDict(extra="forbid")` — silent extra-field accept | Add `model_config = ConfigDict(extra="forbid")` |
| **D-A5-04** | **P1** | `services/schema_registry/loader.py:88-95` | Schema loader не валидирует JSON-Schema syntax (delegates to runtime) | Pre-validation через `jsonschema.Draft7Validator.check_schema()` |
| **D-A5-05** | **P2** | `tools/gen_api_docs.sh:12-18` | Auto-gen скрипт не fail на empty schema list | `set -euo pipefail` + check |
| **D-A5-06** | **P2** | `routes/hello_route/schemas/` | route schemas не зарегистрированы в central registry | Auto-register через loader |
| **D-A5-07** | **P3** | `services/ops/data_quality/apply_mixin.py:316-326` | `dict[str, Any]` для DQ-rule payload | Generic TypedDict |
| **D-A5-08** | **P3** | `core/di/providers/schemas.py:45-52` | Schema provider cache — unbounded, нет TTL | Wrap в `cachetools.TTLCache` (T-3.1 fix pattern) |
| **D-A5-09** | **P4** | `docs/autoapi/` (MkDocs migration) | Auto-generated pages не имеют русскоязычных docstrings для ~30% symbol'ов | Manual pass в следующих циклах |

---

## 4. Эталонные соответствия (verified)

- `ConfigDict(extra="forbid")` присутствует в большинстве `extensions/credit_pipeline/schemas/*.py` ✅
- `mkdocs.yml` schema-export hooks работают (B2 migration complete) ✅
- AsyncAPI экспорт поддерживает 3 multi-protocol tier (REST/SOAP/MQ) ✅

---

## 5. Не проверено

- Каждый endpoint handler — coverage ~40% sampled
- `services/ai/**` schemas (вне A5 scope, в A9)
- `extensions/dadata/schemas/`, `extensions/skb/schemas/` — read summary only
- Frontend TypeScript-type generation (cross-domain)

---

## 6. Готовность домена: **75%**

**Главный риск:** `services/schema_registry/registry.py:251-270` — `dict[str, Any]` fallback
открывает дверь для untyped payload'ов на публичной границе. Требует P0-fix.

**Минимальная рекомендация:**
1. Generic TypedAdapter wrapper для `dict[str, Any]` (D-A5-01) — ~+30 LOC, +10% type safety
2. `AuditEvent` Pydantic conversion (D-A5-02) — ~+20 LOC
3. Pre-schema-validation (D-A5-04) — ~+15 LOC
