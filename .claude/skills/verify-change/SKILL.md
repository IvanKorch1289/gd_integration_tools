---
name: verify-change
description: Самопроверка изменений через минимально достаточные команды Makefile.
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash(make lint) Bash(make lint-strict) Bash(make type-check) Bash(make type-check-strict) Bash(make deps-check) Bash(make deps-check-strict) Bash(make secrets-check) Bash(make routes) Bash(make actions) Bash(make docs) Bash(make readiness-check)
---

# Verify Change

Проведи самопроверку для изменений: $ARGUMENTS

Правила:
1. Выбери минимально достаточный набор проверок.
2. Не запускай лишнее без причины.
3. Для Python-кода используй `make lint` и/или `make type-check`.
4. Для DI/DSL/contracts добавь `make routes` и `make actions`.
5. Для документации используй `make docs`.
6. Для чувствительных изменений используй `make readiness-check`.
7. Верни:
   - какие команды запускались;
   - что прошло;
   - что не прошло;
   - блокирует ли это завершение.