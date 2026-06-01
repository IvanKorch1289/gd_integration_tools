# Как пользоваться настройками Claude в gd_integration_tools

## Что лежит в проекте
- `CLAUDE.md` — главный системный контекст проекта
- `.claude/settings.json` — project settings, permissions, hooks, оптимизация токенов
- `.claude/settings.local.example.json` — пример личных локальных настроек
- `.claude/rules/` — длинные правила
- `.claude/skills/` — сценарии работы
- `.claude/agents/` — специализированные субагенты
- `.claude/commands/` — slash-команды
- `.mcp.json` — проектные MCP
- `.githooks/post-commit` — автообновление graphify после коммита

## Первый запуск
1. Скопируй файлы в корень репозитория
2. Сделай локальный файл `.claude/settings.local.json` при необходимости
3. Включи git hook:
   ```bash
   git config core.hooksPath .githooks
   chmod +x .githooks/post-commit
   ```
4. Убедись, что переменная `GITHUB_TOKEN` выставлена в окружении, а не в `.env`
5. Открой Claude Code в корне репозитория

## MCP
По умолчанию подключены:
- github
- filesystem
- sequential-thinking
- memory

Это базовый, компактный набор для анализа, ревью, рефакторинга и развития проекта.

## Как ставить задачи
### Рефакторинг
```text
/plan refactor src/services/example.py
```
После подтверждения подключай skill `refactor`.

### Новая фича
```text
/plan feature <название>
```
После подтверждения подключай skill `new-feature`.

### Новый коннектор
```text
/plan connector <тип> <назначение>
```
После подтверждения подключай skill `connector-builder`.

### Workflow / DSL
- `/dsl-review` — аудит покрытия DSL
- skill `workflow-builder` — работа над движком workflow
- skill `dsl-expansion` — расширение DSL

### Документация и портал
- `/portal-docs` — обновить developer portal
- skill `developer-portal` — писать/обновлять документацию

## Slash-команды
- `/plan <задача>` — только план
- `/review` — ревью изменённых файлов
- `/test-gen <цель>` — генерация тестов
- `/dead-code` — поиск мёртвого кода
- `/deps-audit` — аудит зависимостей
- `/dsl-review` — аудит DSL
- `/portal-docs` — документация и portal
- `/compact` — сжатие контекста и сохранение прогресса

## Как уменьшать токены
- Не проси Claude читать весь репозиторий сразу
- Сначала работай через `graphify-out/GRAPH_REPORT.md` и `graphify-out/wiki/index.md`
- Используй skills и subagents вместо длинных одноразовых промптов
- После завершения этапа запускай `/compact`
- Не подключай лишние MCP
- Длинные правила храни в `.claude/rules/`, а не в `CLAUDE.md`

## Безопасность
- Не хранить реальные токены в репозитории
- Использовать переменные окружения для MCP
- `.env` и `secrets/` защищены deny-правилами
- Для локальных послаблений использовать только `.claude/settings.local.json`, не коммитить его
