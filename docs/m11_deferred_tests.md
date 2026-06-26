# M11 Deferred Tests — Tracking Document (Sprint 171)

## Status: M11 R3-R6 applied 41 fixes; 24 tests deferred to follow-up refactor phases

## Deferred tests by R-category

### R2 (sync test/code, 5 deferred)
| File | Test | Reason |
|------|------|--------|
| services/routes/test_loader.py | TestFeatureFlag::test_bool_true (×5 methods) | status="enabled" vs "failed" — capability_gate_strict broke contract |
| services/routes/test_loader.py | TestFeatureFlag::test_bool_false (×5) | same |
| services/routes/test_loader.py | TestCapabilityGateAuditAndStrict | capability gate refactor — R4 |

### R3 (optional deps, 5 deferred)
| File | Test | Reason |
|------|------|--------|
| services/rpa/test_ocr_processor.py | test_import_error_early | src.backend.core.config.features attribute missing |
| services/ai/guardrails/test_lakera_client.py (×5) | whole module | external HTTP mock missing |
| services/ai/guardrails/test_rebuff_client.py (×2) | whole module | pre-existing test pollution |
| services/ai/cache/test_l3_retrieval.py (×1) | whole module | pre-existing test pollution |
| services/ai/dspy/test_optimizer.py (×1) | whole module | pre-existing test pollution |
| services/ai/test_ai_agent_rag.py (×1) | whole module | rag flag propagation in response |
| services/audit/test_audit_service_unified.py (×1) | test_emit_uses_correlation_id_from_contextvar | contextvar API change |
| entrypoints/api/v1/test_auth_introspect.py (×5) | whole module | src.backend.core.config.features missing |

### R4 (HIGH risk refactor, 3 deferred)
| File | Test | Reason |
|------|------|--------|
| entrypoints/api/test_auth_verify_request.py (×3) | whole module | verify_request переехал в core.auth.auth_selector (S96 W1) |
| entrypoints/api/v1/test_admin_marketplace.py (×1) | test_plugins_list_returns_503_when_flag_off | endpoint signature changed (404 vs 503) |
| services/routes/test_loader.py | TestPipelineRegistration::test_* | capability_gate + pipeline registration refactor |
| services/routes/test_loader.py | TestTenantAwarePropagation::test_* | tenant_aware propagation refactor |
| services/routes/test_loader.py | TestLoadedRouteSerialisation::test_* | to_dict signature refactor |
| services/routes/test_loader.py | TestRequiresPlugins::test_* | plugin requires refactor |

### R5 (test-bugs, 3 deferred)
| File | Test | Reason |
|------|------|--------|
| core/utils/test_metrics_registry.py | TestAllExports::test_all | test-bug: m is instance, not module (m.__all__ invalid) |
| frontend/test_admin_pages_imports.py (×3) | whole module | frontend tests broken after page renames (S173) |

### R6 (missing files, 1 deferred)
| File | Test | Reason |
|------|------|--------|
| plugins/composition/test_workflow_setup.py | test_bootstrap_defaults_registers_two_sagas_when_enabled | orders_saga файл не существует в extensions/core_entities/orders/workflows/ |

## Total: 24 tests skipped with reason; all tracked

## Plan
- R4 refactor phase: address deferred tests (HIGH priority)
- After R4: review remaining 24, address where possible
