---
name: research-current-tech
description: Найти актуальные данные по библиотекам, версиям, changelog и современным паттернам разработки.
user-invocable: true
allowed-tools: mcp__context7__resolve-library-id mcp__context7__query-docs mcp__duckduckgo__search mcp__duckduckgo__fetch_content mcp__fetch__fetch WebSearch WebFetch Read
---

# Research Current Tech

Используй этот skill, если нужно:
- проверить актуальную версию библиотеки;
- найти breaking changes;
- сравнить новые подходы;
- изучить официальный паттерн интеграции;
- проверить свежую документацию API.

## Инструменты (в порядке предпочтения)

1. **Context7 MCP** (`mcp__context7__*`) — **первичный** для документации/API/конфигурации библиотек. Версионная официальная документация. Использовать ВСЕГДА для библиотечных вопросов, даже про популярные (FastAPI, Pydantic, SQLAlchemy, Temporal, httpx, structlog). Поток: `resolve-library-id` → `query-docs` с темой.
2. **DuckDuckGo MCP** (`mcp__duckduckgo__*`) — для сравнений, статуса, GitHub issues, миграционного опыта, blog-постов.
3. **Fetch MCP** (`mcp__fetch__fetch`) — углублённое чтение 1–2 страниц.
4. **WebSearch / WebFetch** — fallback при недоступности MCP.

## Порядок

1. Сначала уточни библиотеку/технологию и цель поиска.
2. Если вопрос про API/конфигурацию/синтаксис — начать с **Context7**:
   - `resolve-library-id` → каноническое имя.
   - `query-docs` → конкретная тема (`"async retry policy"`, `"transaction context manager"`).
3. Если вопрос про сравнение/статус/мнения сообщества — начать с **DuckDuckGo MCP** узким запросом.
4. Если search недостаточен — fetch только 1–2 лучших источника.
5. Верни:
   - что найдено (Context7-цитаты помечать `[ctx7: <library>@<version>]`, веб-источники — с URL и датой);
   - что актуально;
   - что это значит для проекта;
   - нужно ли менять текущий код/подход.