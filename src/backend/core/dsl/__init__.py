"""S115 W1 — core/dsl package: Protocol-базированная инверсия зависимостей.

Содержит :mod:`core.dsl.protocols` с минимальными контрактами для DSL
(CommandRegistry, Pipeline, ExecutionEngine). Core/services/entrypoints
импортируют ЭТИ Protocol'ы вместо ``src.backend.dsl.*`` — что устраняет
114 dsl.* layer violations (S113 W3 classified).

DSL-имплементации остаются в ``src/backend/dsl/`` и реализуют Protocol'ы
(duck typing + ``runtime_checkable`` для isinstance checks).
"""
