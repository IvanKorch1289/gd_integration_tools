# context/ — общий bootstrap для обоих агентов

> **Оба агента** (Claude Code и Kimi Code) читают **`BOOTSTRAP.md`** при старте сессии.
> Это **единая точка входа** для контекста проекта, команд и правил.

## Содержимое

- **`BOOTSTRAP.md`** — главный файл. Оба агента должны прочесть его **при старте** сессии.
- `README.md` — этот файл (указатель).

## Как подключить к агентам

- **Claude Code** → добавь в `CLAUDE.md` строку `## Прочти .shared/context/BOOTSTRAP.md при старте`
- **Kimi Code** → добавь в `AGENTS.md` ту же строку

(Прямой `@include` пока не поддерживается обоими агентами.)

## Что содержится в BOOTSTRAP.md

1. **Сначала прочти** — порядок чтения файлов (PLAN.md, vault/SESSIONS.md, ...)
2. **Контекст проекта** — краткая сводка (стек, слои, ключевые элементы)
3. **Команды** — sync-команды (`make sync-*`), quality-команды, graphify
4. **Правила работы** — запрещено, обязательно, рекомендуется, стиль ответов
5. **Vault** — read permissions и что где лежит
6. **Skills** — slash-команды
7. **Если что-то непонятно** — fallback chain перед вопросом к Ivan'у

## Фазы реализации

- ✅ Фаза 3: BOOTSTRAP.md (этот commit)
- ⏳ Фаза 4: session-start/session-close hooks (vault/SESSIONS.md)
- ⏳ Фаза 5: graphify-aliases.sh + TECH_DEBT.md
- ⏳ Фаза 6: smoke-тест (реальный запуск Claude + Kimi)
