# ADR-035: Choice JMESPath-форма как первичный способ описания condition

- **Статус:** accepted
- **Дата:** 2026-04-30
- **Фаза:** Wave-G-W26.1
- **Автор:** crazyivan1289

## Контекст

`ChoiceProcessor` в DSL поддерживал только Python-callable в качестве
predicate:

```python
ChoiceProcessor(
    when=[(lambda ex: ex.in_message.body.get("status") == "ok",
           [DispatchActionProcessor("orders.update")])],
    otherwise=[LogProcessor(level="warning")],
)
```

Это блокирует write-back round-trip (W25 / Wave F): `to_spec()` для
такого Choice вынужден возвращать `None`, потому что callable нельзя
сериализовать в YAML без потери семантики. В аудите `to_spec_audit.md`
Choice — единственный из пяти control-flow процессоров, для которого
write-back в принципе невозможен в legacy-форме.

Параллельно проект уже использует JMESPath в нескольких местах:
`src/dsl/transform/__init__.py:26`, `src/infrastructure/workflow/executor.py:500`.
Зависимость зафиксирована в production-стеке (см. `pyproject.toml`).

## Рассмотренные варианты

- **Вариант 1 — JMESPath (выбран).** `ChoiceBranch(expr=<jmespath>,
  processors=[...])`. Плюсы: читается людьми и UI; уже есть зависимость;
  стандарт AWS/k8s; рантайм-eval тривиален (`bool(jmespath.search(expr,
  body))`). Минусы: не поддерживает доступ к headers/properties без
  расширения схемы выражения.

- **Вариант 2 — jq.** Аналогично JMESPath, но мощнее. Минусы:
  тяжёлая Python-обвязка (pyjq требует libjq), отдельная зависимость,
  больше surface для security-аудита.

- **Вариант 3 — expr-engines (CEL/Starlark).** Универсальные движки
  условных выражений. Минусы: неоправданная сложность для текущего
  скоупа; новые зависимости; обучение пользователей.

- **Вариант 4 — Sandboxed Python eval.** Использование RestrictedPython
  или asteval. Минусы: security-риск, сложность валидации, производит
  тот же эффект, что callable, но с более слабой safety-гарантией.

## Решение

Ввести `ChoiceBranch(expr=<jmespath>, processors=[...])` как **первичный**
способ описания ветвления Choice. Legacy-форма с Python-callable
сохраняется ради обратной совместимости и in-process тестов; для таких
веток `to_spec()` возвращает `None` (write-back пропускает Choice
полностью).

Сериализация в YAML:

```yaml
- choice:
    when:
      - expr: "status == 'ok'"
        processors:
          - dispatch_action: {action: orders.update}
    otherwise:
      - log: {level: warning}
```

Eval в рантайме: `bool(jmespath.search(expr, exchange.in_message.body))`.

## Последствия

- **Положительные:**
  - Write-back полный для нового кода (Choice больше не блокирует
    round-trip);
  - YAML-описание Choice читаемо и редактируемо в UI;
  - Семантика evaluation детерминированная (без side-effect'ов в
    predicate, типичных для Python-lambdas).

- **Отрицательные / трейд-оффы:**
  - JMESPath-выражение работает только над `exchange.in_message.body`;
    обращение к headers/properties требует preprocess'а через
    `transform` или ввода нового scope-API в будущем;
  - Legacy-маршруты с callable-predicate при write-back теряют ветку
    Choice (молча, по политике W25). Если это критично — нужно
    отрефакторить под `expr` или оставить YAML как источник истины.

- **Миграция v2→v3 не требуется:** новое поле `expr` опционально, V2-spec'и
  без `expr` остаются валидными (старый формат не использовал
  declarative-Choice вообще, поэтому никаких существующих YAML с
  callable-predicate нет — write-back раньше пропускал такие ветки).

## Открытые вопросы

- Расширение scope JMESPath (headers / properties / context) —
  будет рассмотрено в W26+ при необходимости от пользователей.
- Валидация выражения на стадии загрузки YAML (compile-time check) —
  можно добавить позже как отдельную задачу.
