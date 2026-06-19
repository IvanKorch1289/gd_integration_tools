"""Sprint 7 K4 AI+RAG + K3 DSL+Workflow feature-flags (T1.3.15 split from core.config.features.__init__).

Извлечено 5 flags (S38 P1.1 W1 T1.3.15):
- Sprint 7 K4 AI+RAG (3):
  - multi_agent_supervisor_enabled (Sprint 7 K4 W0)
  - voice_image_gen_enabled (Sprint 7 K4 W0)
  - voice_stt_tts_enabled (Sprint 7 K4 W0)
- Sprint 7 K3 DSL+Workflow (2):
  - dsl_blueprints_migrate (Sprint 7 K3 W0, wave:s7/k3-dsl-blueprints-migrate)
  - workflow_versioning_strict (Sprint 7 K3 W0, wave:s7/k3-workflow-versioning)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Sprint7Flags(BaseSettings):
    """Sprint 7 K4 AI+RAG (multi-agent + voice/image) + K3 DSL+Workflow.

    Owner: K4 AI/RAG, K3 DSL/Workflow.

    Per S38 T1.3.15, извлечено из monolithic ``core.config.features.FeatureFlags``.

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.sprint7 import Sprint7Flags
        class FeatureFlags(..., Sprint7Flags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    # ─── Sprint 7 — К4 AI+RAG (multi-agent + voice/image) ─────────────────
    multi_agent_supervisor_enabled: bool = Field(
        default=True,
        title="K4 S7: LangGraph multi-agent supervisor (handoff между специализированными агентами)",
        description=(
            "K4 Sprint 7. Owner: K4 AI/RAG. ETA: S7. "
            "Активирует MultiAgentSupervisor (services/ai/multi_agent/supervisor.py) — "
            "LangGraph supervisor pattern + handoff_to(agent_name) tool. "
            "Reference implementation для credit-pipeline "
            "(supervisor=credit_orchestrator, agents=[scoring_agent, document_parser_agent, decision_agent]). "
            "default-OFF до staging-smoke с реальным LLM-провайдером."
        ),
    )

    voice_image_gen_enabled: bool = Field(
        default=True,
        title="K4 S7: Voice (Whisper STT + Coqui TTS) + Image generation wrappers",
        description=(
            "K4 Sprint 7. Owner: K4 AI/RAG. ETA: S7. "
            "Активирует WhisperSTTService / CoquiTTSService (services/ai/voice/) + "
            "LiteLLMImageGenerationService (services/ai/image_generation/litellm_image.py). "
            "Lazy-import openai-whisper / TTS / litellm.image_generation(). "
            "default-OFF до установки voice extras и staging-smoke."
        ),
    )

    voice_stt_tts_enabled: bool = Field(
        default=True,
        title="K4 S7: Whisper STT + Coqui TTS wrappers (voice pipeline)",
        description=(
            "K4 Sprint 7. Owner: K4 AI/RAG. ETA: S7. "
            "Активирует WhisperSTTService.transcribe() / CoquiTTSService.synthesize() "
            "поверх openai-whisper и Coqui TTS (extras [ai-voice]). "
            "Lazy-import тяжёлых SDK; default-OFF до установки extras и staging-smoke."
        ),
    )

    # ─── Sprint 7 — K3 DSL+Workflow ────────────────────────────────────────
    dsl_blueprints_migrate: bool = Field(
        default=True,
        title="K3 S7: deprecation-warning для legacy импортов src.backend.dsl.macros",
        description=(
            "K3 Sprint 7 (wave:s7/k3-dsl-blueprints-migrate). Owner: K3 DSL/Workflow. "
            "ETA: S7. Активирует DeprecationWarning при импорте через shim "
            "'from src.backend.dsl.macros import X' — реальная реализация теперь "
            "в src.backend.dsl.blueprints.macros. default-OFF (1-2 sprint grace-period). "
            "После Sprint 9 shim удаляется."
        ),
    )

    workflow_versioning_strict: bool = Field(
        default=True,
        title="K3 S7: strict workflow versioning + Temporal patched-API integration",
        description=(
            "K3 Sprint 7 (wave:s7/k3-workflow-versioning). Owner: K3 DSL/Workflow. "
            "ETA: S7. Активирует WorkflowVersionRegistry strict-mode: "
            "несовместимая мажорная версия → ValueError на register; "
            "интеграция с temporalio.workflow.patched(patch_id) для миграций между "
            "версиями. default-OFF до интеграции с Temporal cluster и staging-smoke."
        ),
    )


__all__ = ("Sprint7Flags",)
