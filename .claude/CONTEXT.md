# CONTEXT.md

## Текущее состояние (2026-05-27 14:30, S33 closure)

**HEAD**: `1a383b15` — S27 Wave 3: admin-react bridge + SessionList + components
**Session summary**: `vault/session-2026-05-27-1430-summary.md`

---

### S33 Developer Experience & Platform — CLOSED ✅

| Wave | Файл | Результат |
|------|------|-----------|
| W1 `make wizard-route` | `tools/wizards/{route_wizard,route_templates}.py` | Typer CLI, 6 sources, 6 sinks, AI/retry/SLO/tenant |
| W2 `make wizard-plugin` | `tools/wizards/plugin_wizard.py` | Plugin scaffold: plugin.toml + __init__.py + plugin.py |
| W3 Streamlit health | `src/frontend/streamlit_app/pages/65_Services.py` | Live httpx health-ping, status badges |
| W4 OpenAPI import | `tools/import_swagger.py` | `--resolve-refs` + `--split` + `--verbose` + snake_case |
| W5 VSCode extension | `tools/vscode-extension/{package.json,extension.ts}` | 5 commands, DSL languages |

### Исправленные баги (S33)

- `65_Services.py`: removed unused `sys` import + `health` variable; fixed return type `tuple[ServiceStatus, int | None]`; added `noqa: S110`
- Ruff: All checks passed на всех изменённых файлах

### Code review findings (5 confirmed, none critical)

1. **DRY** — route_templates.py дублирует константы из route_wizard.py (accepted, self-contained)
2. **Import path** — plugin_wizard генерирует `gd_integration_tools.core.plugin_runtime.BasePlugin` (работает через uv run, но путь не каноничен)
3. **Magic number** — `response.status_code < 500` без константы
4. **Broad exception** — `_ping_url` ловит `Exception` вместо `httpx.RequestError`
5. **Empty init** — `tools/wizards/__init__.py` без `__all__`

---

### Следующий шаг

**S34 W1**: Sphinx auto-api + Diátaxis structure + pre-push docstring gate + coverage 90%

---

### Открытые риски

1. **(LOW) plugin_wizard import path** — проверить при живом тесте сгенерированного плагина
2. **(LOW) route_templates DRY** — можно слить константы в shared модуль
3. **(INFO) ruff false positive** — extension.ts TypeScript ошибки от ruff (не баг)

### Проверки

```bash
uv run ruff check tools/wizards/ tools/import_swagger.py src/frontend/streamlit_app/pages/65_Services.py  # All passed
python tools/wizards/route_wizard.py --help
python tools/wizards/plugin_wizard.py --help
uv run python tools/import_swagger.py --help
```