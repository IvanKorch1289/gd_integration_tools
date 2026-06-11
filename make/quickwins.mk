##@ K5 S19 W4 — quick-wins-pack (new-adr + completions + release-notes)
##@ K5 S19 W4 — quick-wins-pack (new-adr + completions + release-notes)

new-adr: ## Создать новый ADR из шаблона (TITLE="Заголовок ADR" [NUMBER=123])
	@if [ -z "$(TITLE)" ]; then \
		echo "Использование: make new-adr TITLE=\"Мой новый ADR\""; \
		exit 1; \
	fi
	$(UV_RUN) python tools/new_adr.py "$(TITLE)" $(if $(NUMBER),--adr-number $(NUMBER),)

adr-index: check-env ## S42 W3: перегенерировать docs/adr/INDEX.md
	@$(INFO) "Generating ADR index..."
	$(UV_RUN) python tools/generate_adr_index.py
	@$(SUCCESS) "ADR index updated"

release-notes: ## Сгенерировать release-notes из wave-tags в git log (FROM=v0.1.0 TO=v0.2.0)
	$(UV_RUN) python tools/changelog_autogen.py $(if $(FROM),--from $(FROM),) $(if $(TO),--to $(TO),) $(if $(OUTPUT),--output $(OUTPUT),)


# ---------------------------------------------------------------------- #
# V22 Sprint 37 W1 — sync Claude Code ↔ Kimi Code через .shared/         #
# Фаза 0-1: каркас + permissions sync. Логика MCP в фазе 2.              #
# ---------------------------------------------------------------------- #
.PHONY: sync-agents sync-mcp sync-permissions sync-permissions-verify verify-permissions session-start session-close vault-index


