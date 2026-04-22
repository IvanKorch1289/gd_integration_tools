---
name: workflow-builder
description: Воркфлоу создания или расширения workflow-движка проекта
---

## Контекст
Проект — шина интеграции. Workflow должны поддерживать:
- Выполнение бизнес-логики
- Ветвление (условия)
- Циклы
- Запуск subworkflows
- Запуск в отдельном потоке/процессе

## Шаг 1 — Анализ текущего движка
```bash
graphify explain "workflow"
Read: src/workflows/
```

## Шаг 2 — Выбор/подтверждение движка
Варианты для интеграции: Temporal, Prefect, Celery, Dramatiq.
Предложить лучший вариант для проекта с обоснованием. СТОП, жди подтверждения.

## Шаг 3 — Реализация
1. Движок в `src/infrastructure/workflow_engine.py`
2. DSL-описание workflow → `src/dsl/workflow.py`
3. Визуализация в Streamlit → `src/static/streamlit_app.py`
4. Регистрация в DI → `src/core/svcs_registry.py`

## Шаг 4 — Тесты
Субагент `test-generator`
