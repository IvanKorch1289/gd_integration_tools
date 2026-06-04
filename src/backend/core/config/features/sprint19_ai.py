"""Sprint 19 AI/Resilience/UI feature-flags (T1.3.24 split from core.config.features.__init__).

Извлечено 11 flags (S38 P1.1 W1 T1.3.24) — вторая половина Sprint 19
(после T1.3.23 взял первые 12 K3/K4/K5 DSL+AI+DX, эта порция — оставшиеся
AI/Resilience/UI/security из K1/K2/K4/K5):

- K1 Security (4):
  - vault_zero_downtime_rotation (S19 W1)
  - current_frames_fallback (S19 W2)
  - ai_safety_capability_unify (S19 W5)
  - prod_hot_reload_disable (S19 W6)
- K2 Resilience (3):
  - multi_replica_failover (S19 W1)
  - manage_py_diagnose (S19 W2)
  - adaptive_timeout_enabled (S19 W3)
- K4 AI/RAG (1):
  - adaptive_rag_strategy_enabled (S19 W6)
- K5 Frontend/DX (3):
  - quick_wins_pack (S19 W4)
  - admin_react_mvp (S19 W5)
  - dsl_usage_audit_enabled (S19 W6)  # владение K3 DSL, но wave S19 W6 → S19 group

Итого: 11 flags.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Sprint19AIFlags(BaseSettings):
    """Sprint 19 вторая половина: AI/Resilience/UI/security (K1+K2+K4+K5).

    Per S38 T1.3.24, извлечено из monolithic ``core.config.features.FeatureFlags``.
    Первая половина Sprint 19 (12 flags, K3/K4/K5 DSL+AI+DX waves) — отдельный split
    (T1.3.22/T1.3.23); здесь — оставшиеся 11 (adaptive_timeout ... quick_wins).

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.sprint19_ai import Sprint19AIFlags
        class FeatureFlags(..., Sprint19AIFlags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    # ─── Sprint 19 — K2 Resilience (3) ─────────────────────────────────────
    multi_replica_failover: bool = Field(
        default=False,
        title="K2 S19 W1: SmartSessionManager multi-replica failover (S-L6-4)",
        description=(
            "K2 Sprint 19 Wave 1 (PLAN.md V22 §S19 W10, S-L6-4). Owner: K2 Resilience. "
            "При True SmartSessionManager поддерживает multi-replica failover: "
            "replication-lag monitoring через pg_stat_replication + auto-routing по lag-budget. "
            "Chaos test (kill replica) должен проходить. "
            "default-OFF до chaos-test validation."
        ),
    )

    manage_py_diagnose: bool = Field(
        default=False,
        title="K2 S19 W2: manage.py diagnose aggregator JSON output для CI",
        description=(
            "K2 Sprint 19 Wave 2 (PLAN.md V22 §S19 W16). Owner: K2 DevOps. "
            "При True manage.py diagnose выводит JSON со status всех subsystems: "
            "db/redis/kafka/vault/llm-gateway/health/endpoints. "
            "CI-gate: diagnose JSON exit 0 только при all-healthy. "
            "default-OFF до diagnose output schema review."
        ),
    )

    adaptive_timeout_enabled: bool = Field(
        default=False,
        title="K2 S19 W3: .policy.adaptive_timeout(percentile=99, safety_factor=1.5) builder API",
        description=(
            "K2 Sprint 19 Wave 3 (PLAN.md V22 §S19 W15). Owner: K2 Resilience. "
            "При True RouteBuilder и WorkflowBuilder поддерживают "
            ".policy.adaptive_timeout(percentile=99, safety_factor=1.5) — адаптивный "
            "timeout на основе historical latency. "
            "default-OFF до adaptive timeout smoke-test."
        ),
    )

    # ─── Sprint 19 — K1 Security (4) ──────────────────────────────────────
    vault_zero_downtime_rotation: bool = Field(
        default=False,
        title="K1 S19 W1: Vault zero-downtime secret rotation (S-L6-6)",
        description=(
            "K1 Sprint 19 Wave 1 (PLAN.md V22 §S19 W10, S-L6-6). Owner: K1 Security. "
            "При True graceful Vault reconnect: сохранение старого secret N минут drift-toleration + "
            "validation новых credentials ДО активации. "
            "default-OFF до rotation smoke-test."
        ),
    )

    current_frames_fallback: bool = Field(
        default=False,
        title="K1 S19 W2: sys._current_frames() graceful fallback для PyPy/Jython (F-6)",
        description=(
            "K1 Sprint 19 Wave 2 (PLAN.md V22 §S19 W17, F-6 carryover). Owner: K1 Security. "
            "При True tools/checks/check_deadlock.py использует sys._current_frames() "
            "с graceful fallback на PyPy/Jython (где отсутствует). "
            "default-OFF до fallback smoke-test на PyPy."
        ),
    )

    ai_safety_capability_unify: bool = Field(
        default=False,
        title="K1 S19 W5: AI Safety fs.write.<scope> unified capability (ADR-NEW-16/17/18 closure)",
        description=(
            "K1 Sprint 19 Wave 5 (PLAN.md V22 §S19 W19). Owner: K1 Security/AI Safety. "
            "При True AI workspace fs.write.<scope> унифицирован: все write-operations "
            "проходят через AIWorkspaceManager с capability-checked scopes. "
            "fs.write.artifact / fs.write.session / fs.write.tenant. "
            "default-OFF до AI Safety audit."
        ),
    )

    prod_hot_reload_disable: bool = Field(
        default=False,
        title="K1 S19 W6: APP_PROFILE=prod hot-reload disabled",
        description=(
            "K1 Sprint 19 Wave 6 (PLAN.md V22 §S19 W20). Owner: K1 Security/DevOps. "
            "При True hot-reload деактивируется при APP_PROFILE=prod "
            "(settings.app.profile == 'prod'). "
            "default-OFF до prod hot-reload validation."
        ),
    )

    # ─── Sprint 19 — K4 AI/RAG (1) ────────────────────────────────────────
    adaptive_rag_strategy_enabled: bool = Field(
        default=False,
        title="K4 S19 W6: Adaptive RAG strategy finale (dense/hybrid/hyde/multi_query)",
        description=(
            "K4 Sprint 19 Wave 6 (PLAN.md V22 §S19 W18). Owner: K4 AI/RAG. "
            "При True RagQueryProcessor расширяется: dense/hybrid/hyde/multi_query "
            "через LLM-classifier. Accuracy +15% bench. Latency <50ms. "
            "default-OFF до adaptive RAG bench validation."
        ),
    )

    # ─── Sprint 19 — K5 Frontend/DX + K3 DSL (3) ──────────────────────────
    quick_wins_pack: bool = Field(
        default=False,
        title="K5 S19 W4: make new-adr + completions + release-notes + D3.js arch map",
        description=(
            "K5 Sprint 19 Wave 4 (PLAN.md V22 §S19 W16). Owner: K5 DX. "
            'При True: make new-adr TITLE="..." + manage.py completions install + '
            "make release-notes + frontend/streamlit_app/pages/05_Architecture_Map.py (D3.js). "
            "default-OFF до quick-wins review."
        ),
    )

    admin_react_mvp: bool = Field(
        default=False,
        title="K5 S19 W5: frontend/admin-react/ MVP (React-based admin UI)",
        description=(
            "K5 Sprint 19 Wave 5 (PLAN.md V22 §S19 W22). Owner: K5 Frontend. "
            "При True frontend/admin-react/ содержит MVP React admin UI: "
            "routes dashboard + feature-flag toggle + audit viewer. "
            "default-OFF до admin MVP review."
        ),
    )

    dsl_usage_audit_enabled: bool = Field(
        default=False,
        title="K3 S19 W6: DSL usage audit tools/audit/dsl_usage_audit.py",
        description=(
            "K3 Sprint 19 Wave 6 (PLAN.md V22 §S19 W21). Owner: K3 DSL. "
            "При True tools/audit/dsl_usage_audit.py собирает статистику использования "
            "DSL процессоров: top-20 steps, avg latency, error rate per step type. "
            "default-OFF до audit dashboard integration."
        ),
    )


__all__ = ("Sprint19AIFlags",)
