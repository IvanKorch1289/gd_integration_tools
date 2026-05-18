# Build first action

Добавляем первую action и регистрируем route.

## Цель

В конце tutor'а: `POST /api/v1/orders/calculate_credit` возвращает
echo-payload, action виден в `make actions`.

## Шаги

1. Сгенерировать сервис + repository + action:

    ```bash
    make new-service NAME=demos DOMAIN=core CRUD=1 FIELDS='{"title":"str"}'
    ```

2. Подтвердить регистрацию:

    ```bash
    make actions | grep demos
    ```

3. Открыть OpenAPI Swagger: http://127.0.0.1:8000/docs.

## Что дальше

Полноценный плагин с собственными routes — следующий tutor:
[First plugin](02_first_plugin.md).
