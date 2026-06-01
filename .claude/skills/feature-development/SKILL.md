---
name: new-feature
description: Воркфлоу добавления новой фичи с соблюдением архитектуры
---

## Шаг 1 — Исследование
```bash
graphify query "<название фичи>"
graphify path "entrypoints" "services"
```
Ответь: какие существующие модули затронет фича?

## Шаг 2 — План (СТОП, жди подтверждения)
- Список новых файлов
- Список изменяемых файлов
- Новые зависимости (если есть — обоснуй)
- Порядок шагов

## Шаг 3 — Реализация (по одному файлу)
1. Протокол → `src/core/protocols.py`
2. Интерфейс → `src/core/interfaces.py`
3. Сервис → `src/services/<name>.py` (копировать паттерн из существующего)
4. Коннекторы при необходимости → `src/infrastructure/connectors/<name>.py`
5. Регистрация в DI → `src/core/svcs_registry.py`
6. Схемы → `src/schemas/<name>.py`
7. Роутер → `src/entrypoints/<name>.py`
8. DSL-покрытие → `src/dsl/<name>.py` (если применимо)
После каждого файла: `make lint`

## Шаг 4 — Тесты
Запусти: субагент `test-generator`

## Шаг 5 — Финал
```bash
make test
make lint
graphify update .
```
