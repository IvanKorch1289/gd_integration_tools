# Tutorial — Build your first Action

Цель: добавить новый action и убедиться, что он автоматически
становится доступен через REST + DSL + MCP.

## Что вы узнаете
- Как описать action через `ActionSpec`.
- Как зарегистрировать service.
- Как проверить регистрацию.

## Шаги

1. Создайте сервис `src/services/example/hello_service.py`:
   ```python
   class HelloService:
       async def greet(self, *, name: str) -> dict[str, str]:
           """Возвращает приветствие."""
           return {"message": f"Hello, {name}!"}
   ```
2. Добавьте endpoint `src/entrypoints/api/v1/endpoints/hello.py`
   через `ActionRouterBuilder.add_actions(...)`.
3. Подключите router в `routers.py`.
4. Перезапустите `make dev-light`.

## Проверка
- `curl -X POST http://localhost:8000/api/v1/hello/greet -d '{"name":"world"}'`
  → `{"message": "Hello, world!"}`.
- `make actions | grep hello` показывает action.

## Next steps
- [Build a REST connector](build-rest-connector.md)
- [Write a DSL route](write-dsl-route.md)
