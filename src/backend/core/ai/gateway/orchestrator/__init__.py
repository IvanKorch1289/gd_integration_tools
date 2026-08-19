"""Sprint 13 P1-15: dedup — orchestrator subpackage был дубликатом gateway_orchestrator_mixin.

Per Ponytail: один implementation → не нужен wrapper. Удалён enforced_invoke.py
(482 LOC), использовался только в этом __init__. Канонический EnforcedInvokeMixin —
в ``src.backend.core.ai.gateway_orchestrator_mixin`` (используется в
``src.backend.core.ai.gateway.gateway`` + 7+ tests).

Module оставлен как маркер для будущих subpackage extensions (если
потребуется выделить более специфичные orchestrators).
"""
