"""Sprint 6 К5 chaos-suite — 11 chains × 3 scenarios = 33 теста.

Все тесты помечены маркером ``chaos`` + ``requires_toxiproxy``.
В CI выполняются с ``--continue-on-error`` (warn-only) до Sprint 9, когда
feature-flag ``chaos_tests_blocking`` будет переведён в ON.
"""
