# Audit callsite migration — soft-deprecation policy (S105 W2)

**Status:** S105 W2 — deprecate-only path (consult decision B от subagent-2 finding).
**Date:** 2026-06-13
**Source:** DEEP-RESEARCH §3.4 + subagent-2 architectural analysis (2026-06-13).

---

## 1. Проблема (subagent-2 finding)

Legacy ``_emit_audit()`` / ``_emit_audit_safe()`` callsites (77 штук в
23 файлах) **НЕ drop-in replaceable** с canonical ``emit_audit()`` facade.

**Две несовместимые архитектуры:**

| | Architecture A (legacy, 50 callsites) | Architecture B (new facade, 16 users) |
|---|---|---|
| **Mechanism** | ``self._audit: Callable[[dict], None]`` — DI callback | ``get_unified_audit_service()`` — service-locator |
| **Testable via** | injected mock callback | global singleton mock |
| **Domain events** | Typed (``WafDecision``, ``AuthorizationDecision``, ``RotationAuditEvent``) | String + kwargs (``event, actor, resource, action, outcome, details``) |
| **Sync/Async** | Mostly sync | Sync facade → async ``AuditService.emit`` |

**Слепая замена сломает ~12 тестов** (DI callback mock pattern) и потеряет
typed-event семантику. Real migration = multi-week refactor.

---

## 2. Решение (deprecate-only)

S105 W2 = **soft deprecation** через ``tools/check_audit_deprecation.py``:

* **Существующие** 77 callsites — **остаются как есть** (zero risk).
* **Новые** callsites — **warnings** через скрипт.
* **Canonical path** для нового кода:
  ```python
  from src.backend.core.audit.facade import emit_audit
  emit_audit(event="...", actor="...", resource="...", action="...")
  ```
* **CI gate** (``--strict`` mode) — для будущих sprints, после baseline
  зафиксирован.

Это даёт:
1. **Visibility** — все знают, сколько legacy осталось.
2. **No new debt** — новые callsites ловятся.
3. **No breaking change** — существующее не ломается.
4. **Future-friendly** — когда выберем migration path (per-domain helpers
   или full refactor), скрипт покажет прогресс.

---

## 3. Tool API

```bash
# Default: report + exit 0 (для pre-commit).
.venv/bin/python tools/check_audit_deprecation.py

# CI gate: exit 1 если есть callsites.
.venv/bin/python tools/check_audit_deprecation.py --strict

# JSON output (для автоматизации).
.venv/bin/python tools/check_audit_deprecation.py --json

# Custom root.
.venv/bin/python tools/check_audit_deprecation.py --root ./src
```

**Output (default):**
```
======================================================================
Audit Deprecation Check (S105 W2 soft-deprecation)
======================================================================
Files scanned: 2232
Files with legacy callsites: 22
Total legacy callsites: 76

[INFO] Legacy callsites by file:
  src/backend/core/security/capabilities/gate/check_mixin.py: 16
  src/backend/dsl/engine/processors/ai_banking/document.py: 7
  ...

[HINT] Per-file locations: re-run with --json for full details, or migrate to canonical facade:
       from src.backend.core.audit.facade import emit_audit
======================================================================
```

---

## 4. Migration path forward (S106+)

Этот doc фиксирует **soft gate**. Реальная migration strategy — отдельное
архитектурное решение. Опции (per subagent-2 report):

### Path A: Per-domain helpers в facade

```python
# core/audit/facade.py
def emit_waf_audit(decision: WafDecision, method: str, url: str) -> Any: ...
def emit_capability_audit(*, plugin, capability, outcome, ...) -> Any: ...
def emit_rotation_audit(*, secret_path, rotation_id, ...) -> Any: ...
```

Per-domain helpers сохраняют typed-event семантику, вызывают ``emit_audit()``
под капотом. Заменяем callsites по 1 domain за sprint. **Effort:** 1-2 дня.

### Path B: Deprecate-only (current, S105 W2)

Soft gate, no breaking change. Existing callsites работают, новые
блокируются (через ``--strict``). **Effort:** 2-3 часа (текущий commit).

### Path C: Full architectural refactor

50 callsites мигрируют на typed events + service-locator pattern.
**Effort:** multi-week. Out of scope S105+.

### Path D: ADR-0189 closure, defer S107+

Зафиксировать конфликт в ADR, отложить до следующего major sprint.
**Effort:** 1-2 часа.

**Рекомендация:** Path A (S106 W1) — pragmatic balance.

---

## 5. Pre-commit integration (deferred)

Текущий pre-commit hook не вызывает ``check_audit_deprecation.py``.
Добавление — отдельный шаг (S106 W2 backlog):

```yaml
# .pre-commit-config.yaml (предложение)
- repo: local
  hooks:
    - id: audit-deprecation-check
      name: Audit callsite deprecation check
      entry: .venv/bin/python tools/check_audit_deprecation.py
      language: system
      pass_filenames: false
      types: [python]
```

**Без strict mode** — pre-commit = warning, не error. CI = ``--strict``.

---

## 6. Out of scope

* Реальный code-migration (Path A/C) — S106+ W1+.
* Pre-commit hook wiring — S106 W2.
* CI gate (`--strict` в ``.github/workflows/lint.yml``) — после baseline
  freeze.
* 8 ``_emit_audit_safe`` callsites — отдельный паттерн, требует
  investigation (sync vs async semantics). S106+ scope.

---

## 7. References

* `tools/check_audit_deprecation.py` (NEW, S105 W2)
* `tests/unit/tools/test_check_audit_deprecation.py` (NEW, 12 tests)
* `~/.hermes/agent_workspaces/task2_audit_migration_report.md` (subagent-2
  full analysis, 17.8 KB)
* `docs/adr/0187-sprint-103-cross-cutting.md` (S103 W3 facade)
* `src/backend/core/audit/facade.py` (canonical location)
* DEEP-RESEARCH §3.4 (original claim: 58 → subagent measured 77)
