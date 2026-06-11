##@ Runtime
##@ Runtime

layers: ## Проверка архитектурных слоёв (ADR-001)
	@uv run python tools/check_layers.py

layers-update: ## Обновить allowlist архитектурных нарушений (после сокращения legacy)
	@uv run python tools/check_layers.py --update-allowlist

side-effect-audit: ## W14.4 — аудит классификации side-effects процессоров
	@$(UV_RUN) python tools/check_side_effects.py --allow-default

dsl-w14-check: layers side-effect-audit ## W14.2-14.4 контракты + side-effects + слои
	@$(SUCCESS) "DSL W14 контракты в порядке"

config-audit: check-env ## Двусторонний аудит конфигов (orphans + missing secrets)
	@$(UV_RUN) python tools/config_audit.py

config-new: check-env ## Интерактивный wizard создания нового Settings-класса
	@$(UV_RUN) python tools/codegen_settings.py wizard

config-apply: check-env ## Применить config-spec/<NAME>.yml (NAME=<name>)
	@if [ -z "$(NAME)" ]; then echo "Использование: make config-apply NAME=<name>"; exit 1; fi
	@$(UV_RUN) python tools/codegen_settings.py apply "config-spec/$(NAME).yml"

config-extract: check-env ## Reverse-codegen: класс → config-spec/<name>.yml (CLS=<Name>Settings)
	@if [ -z "$(CLS)" ]; then echo "Использование: make config-extract CLS=<Name>Settings"; exit 1; fi
	@$(UV_RUN) python tools/codegen_settings.py extract --cls "$(CLS)"

run: check-env ## Start backend in foreground (использует APP_SERVER из env)
	@$(MANAGE_SCRIPT) run

dev: check-env ## Start backend (uvicorn, dev режим)
	@APP_SERVER=uvicorn $(MANAGE_SCRIPT) run

dev-light: check-env ## Start backend (APP_PROFILE=dev_light, без Docker)
	@APP_PROFILE=dev_light APP_SERVER=uvicorn $(MANAGE_SCRIPT) run

prod: check-env ## Start backend (granian, production)
	@APP_PROFILE=prod APP_SERVER=granian $(MANAGE_SCRIPT) run

run-all: check-env ## Start backend + frontend
	@$(MANAGE_SCRIPT) run-all

stop: ## Stop project services
	@$(INFO) "Stopping services..."

restart: check-env ## Restart backend
	@$(MANAGE_SCRIPT) run

status: check-env ## Show project services status
	@$(MANAGE_SCRIPT) health

migrate: check-env ## Apply database migrations
	@$(MANAGE_SCRIPT) migrate

rabbit-init: check-env ## Initialize RabbitMQ entities
	@$(MANAGE_SCRIPT) init-rabbit

frontend: check-env ## Start Streamlit dashboard
	@$(MANAGE_SCRIPT) run-frontend

streamlit: frontend ## Alias: Streamlit dashboard (R3.10c)

scaffold: check-env ## Scaffold new component (usage: make scaffold type=service name=invoices)
	@$(MANAGE_SCRIPT) scaffold $(type) $(name)

scaffold-route: check-env ## Sprint 10 K5 W2: DEPRECATED — use make wizard-route instead
	@echo "use: make wizard-route NAME=... SOURCE=... SINK=..."
	@$(UV_RUN) python tools/scaffold_route.py \
		$(if $(NAME),--name $(NAME),) \
		$(if $(SOURCE),--source $(SOURCE),) \
		$(if $(SINK),--sink $(SINK),) \
		$(if $(AI),--ai,) \
		$(if $(RETRY),--retry,) \
		$(if $(FORCE),--force,)

wizard-route: check-env ## S33 W1: Typer-based route wizard (NAME=... [SOURCE=http SINK=http AI=1 RETRY=1])
	@$(INFO) "Scaffolding route $(NAME)..."
	@$(UV_RUN) python tools/wizards/route_wizard.py \
		$(if $(NAME),--name $(NAME),) \
		$(if $(SOURCE),--source $(SOURCE),) \
		$(if $(SINK),--sink $(SINK),) \
		$(if $(AI),--ai,) \
		$(if $(RETRY),--retry,) \
		$(if $(RETRY_ATTEMPTS),--retry-attempts $(RETRY_ATTEMPTS),) \
		$(if $(AI_MODEL),--ai-model $(AI_MODEL),) \
		$(if $(AI_PROVIDER),--ai-provider $(AI_PROVIDER),) \
		$(if $(TENANT_AWARE),--tenant-aware,) \
		$(if $(P95_MS),--p95-ms $(P95_MS),) \
		$(if $(TIMEOUT_MS),--timeout-ms $(TIMEOUT_MS),) \
		$(if $(FORCE),--force,)

wizard-plugin: check-env ## S33 W2: Typer-based plugin wizard (NAME=...)
	@$(INFO) "Scaffolding plugin $(NAME)..."
	@$(UV_RUN) python tools/wizards/plugin_wizard.py \
		$(if $(NAME),--name $(NAME),) \
		$(if $(DESCRIPTION),--description $(DESCRIPTION),) \
		$(if $(TRUST_TIER),--trust-tier $(TRUST_TIER),) \
		$(if $(REQUIRES_CORE),--requires-core $(REQUIRES_CORE),) \
		$(if $(FORCE),--force,)

routes: check-env ## List DSL routes
	@APP_PROFILE=dev_light $(MANAGE_LIGHT) routes

actions: check-env ## List registered actions
	@APP_PROFILE=dev_light $(MANAGE_LIGHT) actions

actions-strict: check-env ## Wave B: list actions + fail on inferred action_id
	@APP_PROFILE=dev_light $(MANAGE_LIGHT) actions --strict


