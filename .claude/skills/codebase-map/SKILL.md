---
name: codebase-map
description: Построить компактную карту кода и зависимостей для новой или сложной области проекта. Использовать при первом заходе в незнакомый модуль.
disable-model-invocation: false
user-invocable: true
allowed-tools: Read Grep Glob Bash
context: fork
agent: Explore
---

Исследуй область проекта: $ARGUMENTS

Верни:
1. Основные файлы
2. Ключевые импортные связи
3. Публичные интерфейсы
4. Где DSL, DI, schemas и infrastructure пересекаются
5. Какие файлы опасно менять без плана