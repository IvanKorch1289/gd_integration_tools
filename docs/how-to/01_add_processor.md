# Как написать кастомный процессор

Процессоры — это строительные блоки DSL-маршрутов.
Декоратор `@processor` регистрирует функцию в `ProcessorRegistry`.

## Когда использовать

Используйте кастомный процессор, когда встроенных шагов (`call_function`,
`transform`, `choice`) недостаточно и логика переиспользуется в нескольких маршрутах.

## Шаг 1: Создайте файл процессора

Разместите процессор в вашем плагине:

```text
extensions/<name>/processors/my_processor.py
```

## Шаг 2: Зарегистрируйте через `@processor`

```python
# extensions/<name>/processors/my_processor.py
"""Пример кастомного процессора для DSL-маршрутов."""
from src.backend.dsl.registry import processor


@processor(name="my_transform", version="1.0")
async def my_transform(context: dict, *, field: str) -> dict:
    """Трансформирует значение поля в контексте маршрута.

    Args:
        context: Контекст выполнения маршрута (body, headers, meta).
        field: Имя поля в контексте для трансформации.

    Returns:
        Обновлённый контекст с трансформированным полем.
    """
    context["body"][field] = str(context["body"].get(field, "")).upper()
    return context
```

## Шаг 3: Используйте в DSL

```yaml
steps:
  - my_transform:
      field: customer_name
```

## Проверка регистрации

```bash
make actions
```

Ваш процессор появится в списке зарегистрированных обработчиков.

## Важно

- Процессор должен быть `async`.
- Все docstrings — на русском языке (V15 docstring policy).
- Не импортируйте `infrastructure` напрямую — только через capability-checked фасады.
