"""Tests for AIAgentService factory wiring (cycle-5/D-AUDIT-501).

Verifies:
1. :func:`get_ai_agent_service` no longer raises ``NotImplementedError``.
2. DI lookup pattern: ``app.state.ai_agent_service`` → bare :class:`AIAgentService`.
3. Bare construction failure → :class:`AIGatewayProductionWiringError` (fail-closed).
4. Composition-root registered instance is preferred over bare construction.
"""
