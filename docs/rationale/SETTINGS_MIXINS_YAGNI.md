# Settings mixins — YAGNI rationale (M2.2)

**Status:** decision зафиксирован после Sprint A+ (consolidation спринтов).

## Context
`src/backend/core/config/mixins.py` определяет 3 миксина:
`ConnectionMixin` (9 полей), `RetryMixin` (4 поля), `LLMModelMixin` 
(3 поля). Готовы для переиспользования.

## YAGNI-решение: не мигрировать существующие 84 Settings-класса

**Причина:** существующие Settings используют `Field(description=, ge=, le=, 
title=, examples=, default_factory=...)` с rich metadata. Миграция на миксины
(= простые `int = 3`) сломает:
- OpenAPI/JSON-schema documentation (title, description)
- IDE autosuggest (examples)
- Runtime validation constraints (ge, le)
- Custom validators (`model_validator`, `field_validator`)

**Правило для новых Settings-классов:**
1. Проверь, есть ли у тебя `Field(...)` с metadata — если ДА, оставь inline.
2. Если все поля — простые typed (без Field), используй mixin.
3. Если defaults совпадают с mixin defaults — наследуй mixin.
4. Если defaults отличаются — наследуй mixin + override в subclass.

## Tested
- `RetryMixin`, `LLMModelMixin` уже используются в новых Settings-классах S171+.
- Production coverage: ≥5 классов используют миксины (post-M2.2 wave).
