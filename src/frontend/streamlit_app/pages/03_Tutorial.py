"""Краткий туториал для джунов."""

import streamlit as st

st.set_page_config(page_title="Tutorial", layout="wide")
st.header("Быстрый старт: DSL маршрут за 3 минуты")

st.markdown("""
### Что это?

**DSL маршрут** = последовательность шагов обработки данных. Работает через **все протоколы** сразу: REST, gRPC, GraphQL, SOAP, WebSocket, Queue, MCP.

### Анатомия маршрута

```python
from src.backend.dsl.builder import RouteBuilder

route = (
    RouteBuilder.from_("orders.create", source="http:POST:/orders")
    .validate(OrderSchemaIn)          # проверить данные
    .dispatch_action("orders.add")    # сохранить в БД
    .notify(channel="express", to="chat-id")  # уведомить в eXpress
    .log()                             # логирование
    .build()
)
```

### Основные блоки

| Метод | Что делает |
|---|---|
| `.dispatch_action("x.y")` | Вызывает сервис |
| `.validate(Schema)` | Проверяет данные |
| `.transform("expr")` | Преобразует (JMESPath) |
| `.retry(max_attempts=3)` | Повтор при ошибке |
| `.notify(channel, to)` | Email / eXpress / Webhook |
| `.export("excel")` | CSV / Excel / PDF |
| `.call_llm(provider="perplexity")` | Вызов LLM |
| `.log()` | Логирование |

### Exchange — контейнер данных

- `exchange.in_message.body` — входящие данные
- `exchange.properties` — промежуточные значения между шагами
- `exchange.out_message.body` — результат

### Что дальше?

1. **DSL Visual Editor** — собери маршрут мышкой
2. **DSL Playground** — попробуй код с dry-run
3. **Glossary & FAQ** — словарь и частые вопросы
""")
