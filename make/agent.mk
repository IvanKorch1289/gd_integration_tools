##@ Agent sync (Sprint 37 W1 — Claude ↔ Kimi через .shared/)
##@ Agent sync (Sprint 37 W1 — Claude ↔ Kimi через .shared/)

# === ФАЗА 0: STUB для не-реализованных целей ===
sync-agents: ## Фаза 0 stub: проверить наличие .shared/ + vault/, ссылки на будущее
	@if [ ! -d .shared ]; then \
		printf '\033[31m[ERROR] .shared/ не найден.\033[0m\n'; exit 1; \
	fi
	@if [ ! -d vault ]; then \
		printf '\033[31m[ERROR] vault/ не найден.\033[0m\n'; exit 1; \
	fi
	@printf '\033[32m[OK] .shared/ + vault/ на месте.\033[0m\n'
	@printf '\033[33m[INFO] sync-permissions: регенерирует .claude/settings.json + .kimi-code/config.toml.\033[0m\n'
	@printf '\033[33m[INFO] sync-mcp: пока stub (фаза 2).\033[0m\n'

sync-mcp: ## Фаза 2: пересоздать .mcp.json + .kimi-code/mcp.json как symlinks на .shared/mcp-servers.json
	@$(INFO) "Recreating MCP symlinks from .shared/mcp-servers.json..."
	@.venv/bin/python .shared/sync/render_mcp.py
	@$(SUCCESS) "MCP symlinks recreated. Run 'make sync-mcp-verify' to confirm."

sync-mcp-verify: ## Фаза 2: проверить .shared/mcp-servers.json + symlinks + secret-leak scan (exit 1 при проблемах)
	@$(INFO) "Verifying MCP configs (symlinks + secrets)..."
	@.venv/bin/python .shared/sync/render_mcp.py --verify
	@$(SUCCESS) "MCP verified: symlinks OK, no hardcoded secrets."

verify-mcp: sync-mcp-verify

# === ФАЗА 1: РЕАЛЬНАЯ ЛОГИКА ===
sync-permissions: ## Фаза 1: регенерировать .claude/settings.json + .kimi-code/config.toml из .shared/permissions.yaml
	@$(INFO) "Regenerating permissions from .shared/permissions.yaml..."
	@.venv/bin/python .shared/sync/render_permissions.py
	@$(SUCCESS) "Permissions regenerated. Run 'make verify-permissions' to confirm."

sync-permissions-verify: ## Фаза 1: проверить что .claude/settings.json + .kimi-code/config.toml не дрейфуют (exit 1 при дрейфе)
	@$(INFO) "Verifying permissions drift..."
	@.venv/bin/python .shared/sync/render_permissions.py --verify
	@$(SUCCESS) "No drift."

# Алиас
verify-permissions: sync-permissions-verify

# === ФАЗА 4: SESSION LOG + VAULT INDEX (реальная логика) ===
# Валидация AGENT делается внутри bash-скрипта (он сам выдаст ошибку если пусто).
session-start: ## Фаза 4: append-only запись в vault/SESSIONS.md (AGENT=<claude|kimi>, MSG="...")
	@AGENT="$(AGENT)" MSG="$(MSG)" SLUG="$(SLUG)" bash .shared/hooks/session-start.sh

session-close: ## Фаза 4: закрыть последнюю запись для AGENT (AGENT=<claude|kimi>, MSG="...", [CONTEXT=...] [DECISIONS=...] [FILES=...] [NEXT=...])
	@AGENT="$(AGENT)" MSG="$(MSG)" CONTEXT="$(CONTEXT)" DECISIONS="$(DECISIONS)" FILES="$(FILES)" NEXT="$(NEXT)" bash .shared/hooks/session-close.sh

vault-index: ## Фаза 4: regenerate vault/INDEX.md (ls + tail)
	@bash .shared/hooks/vault-index.sh

