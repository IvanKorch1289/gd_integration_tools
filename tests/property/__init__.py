"""Property-based tests via hypothesis (Sprint 35 w4 GAP-AI).

Suites:
    - test_dsl_processor_invariants: idempotency, commutativity, round-trip
    - test_cache_key_invariants: determinism, collision-resistance
    - test_exchange_serialization: serialize → deserialize preserves data
    - test_resilience_state_machine: valid state transitions only
"""
