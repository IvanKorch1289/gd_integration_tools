# sync/ — генераторы конфигов из общего source of truth

> **Наполняется в фазах 1-2.** Сейчас — placeholder.
>
> - `render_permissions.py` — `.shared/permissions.yaml` → `.claude/settings.json`
>   (только секция `permissions`) + `.kimi-code/config.toml` (только `[[permission]]`)
> - `render_mcp.py` — `.shared/mcp-servers.json` → `.mcp.json` +
>   `.kimi-code/mcp.json` (через symlink, фаза 2)
