# .shared/ — общий источник правды для Claude Code и Kimi Code

> **Source of truth** для конфигов и контекста, используемых обоими агентами.
> Структура:
>
> ```
> .shared/
> ├── permissions.yaml         # правила доступа (allow/ask/deny) — единые
> ├── mcp-servers.json         # MCP-конфигурация (Claude + Kimi читают отсюда)
> ├── context/                 # то, что агенты читают при старте сессии
> │   ├── BOOTSTRAP.md         # единая точка входа (фаза 3)
> │   ├── TECH_DEBT.md         # общий ledger техдолга (фаза 3+)
> │   └── graphify-aliases.sh  # общие shell-алиасы для graphify (фаза 5)
> ├── hooks/                   # git pre-commit, session-start, session-close
> └── sync/                    # render_permissions.py, render_mcp.py
> ```
>
> **Принцип:** оба агента читают `.shared/context/BOOTSTRAP.md` при старте.
> Permission rules и MCP генерируются из `.shared/permissions.yaml` и
> `.shared/mcp-servers.json` соответственно (фазы 1, 2).

## Что пока stub (фаза 0)

- `permissions.yaml` — пустой, миграция в фазе 1
- `mcp-servers.json` — пустой, миграция в фазе 2
- `context/BOOTSTRAP.md` — пустой, миграция в фазе 3
- `hooks/*` — пустые, миграция в фазе 4
- `sync/*` — пустые, миграция в фазе 1-2
