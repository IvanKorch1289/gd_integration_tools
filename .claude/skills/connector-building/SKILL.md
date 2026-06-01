---
name: connector-builder
description: Создание нового коннектора (REST/SOAP/gRPC/GraphQL/Queue)
---

## Контекст
Проект — шина интеграции. Коннекторы в `src/infrastructure/connectors/`.
Бизнес-функции должны быть доступны через все коннекторы.

## Шаг 1 — Анализ
```bash
graphify explain "connectors"
ls src/infrastructure/connectors/
```

## Шаг 2 — План (СТОП, жди подтверждения)
- Тип коннектора: REST / SOAP / gRPC / GraphQL / Queue
- Режимы: синхронный / отложенный / фоновый
- Зависимые бизнес-функции

## Шаг 3 — Реализация
1. Протокол → `src/core/protocols.py`
2. Коннектор → `src/infrastructure/connectors/<type>_connector.py`
3. Регистрация в DI
4. DSL-покрытие → `src/dsl/connectors.py`
5. Схемы запроса/ответа

## Шаг 4 — Тесты + ревью
