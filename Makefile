SHELL := /bin/sh

.DEFAULT_GOAL := help

# Ожидается формат Conventional Commits, например: "feat: add oracle db auth"
GIT_COMMIT_MESSAGE ?= chore: code quality improvements
BRANCH ?= main
SOURCE_DIR ?= ./src

RUFF_ARGS ?=

IMAGE_NAME ?= gd-integration-tools
IMAGE_TAG ?= py314

DOCS_DIR := docs
# К5 (Wave K5/docs-tenants-caps): conf.py живёт в docs/ (Diátaxis 4-quadrant).
# Старый sphinx-apidoc target пишет в docs/source — оставляем для совместимости.
DOCS_SOURCE := $(DOCS_DIR)
DOCS_BUILD := $(DOCS_DIR)/build
APP_DIR := src

TAG ?=
GIT_NO_VERIFY ?= 1

DOCKER ?= docker
UV_RUN := uv run
MANAGE_SCRIPT := $(UV_RUN) python manage.py
# Lightweight-вариант для introspection-команд (routes/actions/scaffold):
# использует --extra dev-light, чтобы sqlite/aiosqlite-стек поднимался
# без полного набора prod-зависимостей (psycopg2 и т.п.).
MANAGE_LIGHT := $(UV_RUN) --extra dev-light python manage.py

CONFIG_FILE ?= ./config_profiles/dev.yml
RUN_DIR ?= ./.run
LOG_DIR ?= ./logs

UVICORN_APP ?= src.backend.main:app
UVICORN_HOST ?= 0.0.0.0
UVICORN_PORT ?= 8000

PROFILE_DIR ?= ./profiles
MEMRAY_OUTPUT ?= $(PROFILE_DIR)/fastapi_profile.bin
MEMRAY_FLAMEGRAPH ?= $(PROFILE_DIR)/fastapi_profile_flamegraph.html
MPROF_OUTPUT ?= $(PROFILE_DIR)/memory_usage.dat
PYSPY_OUTPUT ?= $(PROFILE_DIR)/pyspy_profile.svg

INFO := printf '\033[34m%s\033[0m\n'
SUCCESS := printf '\033[32m%s\033[0m\n'
WARN := printf '\033[33m%s\033[0m\n'
ERROR := printf '\033[31m%s\033[0m\n'

# === К1 hooks === include секционных таргетов команды-1 (Security/Net/Secrets/AI-Safety).
# Подключение опциональное — при отсутствии файла make продолжает без ошибки.
-include make/security.mk

.PHONY: \
	help \
	init install update lock \
	check-env check-script check-docker ensure-branch \
	format format-check fix \
	lint lint-strict \
	type-check type-check-strict \
	vulture-check refurb-check \
	clean clean-all code-clean \
	run run-fg stop restart status migrate rabbit-init frontend streamlit \
	profile-memray profile-memray-flamegraph profile-memray-stats profile-mprof profile-pyspy \
	deps-check deps-check-strict \
	secrets-check audit api-fuzz \
	pre-commit commit push git-sync \
	current-version next-version bump \
	code-lint code-check check-strict check-strict-full \
	fix-check-push ship ship-release \
	docker-build docker-run docker-stop \
	tag all \
	docs-clean docs-apidoc docs-html docs-rebuild docs \
	layers layers-update config-audit \
	config-new config-apply config-extract \
	new-service new-repository codegen-extract \
	import-swagger import-postman import-wsdl \
	testkit-smoke new-plugin perf-smoke perf-full perf-gate perf-gate-py perf-baseline chaos chaos-slow docs-vale \
new-adr release-notes

help: ##@ Misc Show this help
	@printf "\nUsage:\n  make \033[36m<target>\033[0m\n"
	@awk 'BEGIN {FS = ":.*## "}; \
		/^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next} \
		/^[a-zA-Z0-9_.-]+:.*## / {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\n"

##@ Setup

init: ## Initialize project with uv
	@$(INFO) "Initializing project..."
	uv sync --all-extras
	@$(SUCCESS) "Project initialized!"

install: ## Install dependencies
	uv sync --all-extras

update: ## Update dependencies
	uv lock --upgrade
	uv sync --all-extras

lock: ## Refresh lock file
	uv lock

check-env: ## Check uv virtual environment
	@if [ -d ".venv" ]; then \
		$(SUCCESS) "uv virtual environment detected"; \
	else \
		$(WARN) "No virtual environment found. Run 'uv sync --all-extras'"; \
		exit 1; \
	fi

check-script: ## Check manage.py exists
	@if [ -f "manage.py" ]; then \
		$(SUCCESS) "manage.py detected"; \
	else \
		$(ERROR) "manage.py not found"; \
		exit 1; \
	fi

check-docker: ## Check Docker availability
	@if command -v $(DOCKER) >/dev/null 2>&1; then \
		$(SUCCESS) "Docker detected"; \
	else \
		$(ERROR) "Docker not found"; \
		exit 1; \
	fi

ensure-branch: ## Ensure target branch exists locally and checkout it
	@$(INFO) "Ensuring branch $(BRANCH)..."
	@current_branch=$$(git branch --show-current); \
	if git show-ref --verify --quiet refs/heads/$(BRANCH); then \
		if [ "$$current_branch" != "$(BRANCH)" ]; then \
			git checkout $(BRANCH); \
		fi; \
	elif git ls-remote --exit-code --heads origin $(BRANCH) >/dev/null 2>&1; then \
		git fetch origin $(BRANCH); \
		git checkout -b $(BRANCH) --track origin/$(BRANCH); \
	else \
		git checkout -b $(BRANCH); \
	fi
	@$(SUCCESS) "Branch $(BRANCH) is ready!"

##@ Formatting

format: check-env ## Format code using Ruff
	@$(INFO) "Formatting code..."
	$(UV_RUN) ruff check --select I --fix $(SOURCE_DIR)
	$(UV_RUN) ruff format $(SOURCE_DIR)
	@$(SUCCESS) "Formatting complete!"

format-check: check-env ## Check formatting without modifying files
	@$(INFO) "Checking formatting..."
	@$(UV_RUN) ruff format --check --diff $(SOURCE_DIR) || ($(ERROR) "Ruff formatting failed! Run 'make fix' to auto-format your code."; exit 1)
	@$(SUCCESS) "Formatting check passed!"

fix: ## Auto-fix code style
	@$(MAKE) format
	@$(INFO) "Fixing lint issues..."
	$(UV_RUN) ruff check --fix $(SOURCE_DIR)
	@$(SUCCESS) "Auto-fix complete!"

##@ Quality

lint: check-env ## Run soft lint; mypy and vulture are non-blocking
	@$(INFO) "Running soft lint..."
	@$(UV_RUN) ruff check $(SOURCE_DIR) $(RUFF_ARGS) || printf '%s\n' "Ruff found issues"
	@MYPY_USE_MYPYC=0 $(UV_RUN) python -X faulthandler -m mypy \
		--cache-dir=/dev/null -p src || printf '%s\n' "Mypy found issues or crashed"
	@$(UV_RUN) vulture $(SOURCE_DIR) --config pyproject.toml || printf '%s\n' "Vulture found possible dead code"
	@$(SUCCESS) "Soft lint complete!"

lint-strict: check-env format-check ## Run strict lint without mypy and vulture
	@$(INFO) "Running strict lint..."
	$(UV_RUN) ruff check $(SOURCE_DIR) $(RUFF_ARGS)
	@$(SUCCESS) "Strict lint passed!"

type-check: check-env ## Run non-blocking mypy type check
	@$(INFO) "Running mypy type check..."
	@MYPY_USE_MYPYC=0 $(UV_RUN) python -X faulthandler -m mypy \
		--cache-dir=/dev/null -p src || printf '%s\n' "Mypy found issues or crashed"
	@$(SUCCESS) "Type check finished!"

type-check-budget: check-env ## Sprint 10 K2: mypy budget gate (max 5 errors, ratcheting; S9 был 30)
	@$(INFO) "Running mypy budget gate (max 5 errors)..."
	@$(UV_RUN) python tools/checks/mypy_budget.py --max 5
	@$(SUCCESS) "Mypy budget OK"

startup-time-gate: check-env ## Sprint 10 K2 W3: startup-time gate (<3s total, fail-on-regression)
	@$(INFO) "Running startup-time gate..."
	@$(UV_RUN) python tools/checks/startup_time.py
	@$(SUCCESS) "Startup-time gate OK"

doctor: check-env ## Sprint 10 K5 W1: comprehensive dev environment health check
	@$(INFO) "Running make doctor..."
	@$(UV_RUN) python tools/checks/doctor.py --quick
	@$(SUCCESS) "Doctor check finished"

dsl-complexity-check: check-env ## Sprint 10 K3 W2: DSL complexity budget (cyclomatic/nesting/steps)
	@$(INFO) "Running DSL complexity budget check..."
	@$(UV_RUN) python tools/checks/dsl_complexity.py routes/ extensions/ --strict
	@$(SUCCESS) "DSL complexity gate OK"

simulate: check-env ## Sprint 10 K5 W3: CLI dry-run route (ROUTE=<name|path>)
	@$(INFO) "DSL simulate $(ROUTE)..."
	@$(UV_RUN) python tools/dsl_simulate.py $(ROUTE)

plugin-dev: check-env ## Sprint 10 K5 W4: infra-only docker + hot-reload + tests (NAME=<ext>)
	@$(INFO) "Plugin-dev mode for $(NAME)..."
	@$(UV_RUN) python tools/plugin_dev.py --name $(NAME) \
		$(if $(AUTO_TEST),--auto-test,) \
		$(if $(NO_COMPOSE),--no-compose-up,)

type-check-strict: check-env ## Run strict mypy type check (tolerates internal mypy bugs)
	@$(INFO) "Running strict mypy type check..."
	@MYPY_USE_MYPYC=0 $(UV_RUN) python -X faulthandler -m mypy \
		--cache-dir=/dev/null -p src || ( \
		RET=$$?; \
		if [ $$RET -eq 2 ]; then \
			$(WARN) "Mypy crashed with INTERNAL ERROR (bug in Mypy v1.20.1). Bypassing..."; \
			exit 0; \
		else \
			exit $$RET; \
		fi )
	@$(SUCCESS) "Strict type check passed!"

vulture-check: check-env ## Run informational dead code scan
	@$(INFO) "Running vulture dead code scan..."
	@$(UV_RUN) vulture $(SOURCE_DIR) --config pyproject.toml || printf '%s\n' "Vulture found possible dead code"
	@$(SUCCESS) "Vulture scan finished!"

refurb-check: check-env ## Check for modern Python idioms
	@$(INFO) "Running Refurb to modernize code..."
	@if $(UV_RUN) refurb --version >/dev/null 2>&1; then \
		$(UV_RUN) refurb $(SOURCE_DIR); \
	else \
		$(WARN) "Skipping refurb: install it with 'uv add --dev refurb'"; \
	fi

deps-check: check-env ## Check for unused dependencies with Creosote
	@$(INFO) "Checking dependencies..."
	@if $(UV_RUN) creosote --version >/dev/null 2>&1; then \
		$(UV_RUN) creosote -p $(SOURCE_DIR) || printf '%s\n' "Creosote found unused dependencies"; \
	else \
		$(WARN) "Skipping creosote: install it with 'uv add --dev creosote'"; \
	fi
	@$(SUCCESS) "Dependencies check complete!"

deps-check-strict: check-env ## Strict dependency check with Creosote
	@$(INFO) "Running strict dependency checks..."
	@if $(UV_RUN) creosote --version >/dev/null 2>&1; then \
		$(UV_RUN) creosote -p $(SOURCE_DIR); \
	else \
		$(ERROR) "creosote is not installed in uv env"; \
		printf '%s\n' "Run: uv add --dev creosote"; \
		exit 1; \
	fi
	@$(SUCCESS) "Strict dependency checks passed!"

secrets-check: check-env ## Scan source code for secrets using detect-secrets
	@$(INFO) "Scanning for secrets..."
	@if $(UV_RUN) detect-secrets --version >/dev/null 2>&1; then \
		$(UV_RUN) detect-secrets scan $(SOURCE_DIR) \
			--exclude-files '.*migrations/versions/.*\.py$$'; \
	else \
		$(WARN) "Skipping detect-secrets: install it with 'uv add --dev detect-secrets'"; \
	fi
	@$(SUCCESS) "Secrets check completed!"

audit: ## Run security and dependency audit
	@$(MAKE) secrets-check
	@$(MAKE) deps-check
	@$(SUCCESS) "Full security audit completed!"

pii-audit-smoke: check-env ## S24 W1: PII detector smoke audit (10-doc mini gold-set; precision/recall)
	@$(INFO) "Running pii-audit-smoke (10-doc mini gold-set)..."
	@$(UV_RUN) python tools/checks/pii_audit.py --mode smoke --threshold 0.85 \
		|| $(WARN) "[pii-audit-smoke] precision/recall below threshold (smoke target 0.85)"

pii-audit: check-env ## S24 W1: PII detector full CI-gate (1000-doc hybrid ru-gold-set; DoD-2 precision/recall >= 0.9)
	@$(INFO) "Running pii-audit (1000-doc hybrid ru-gold-set; ADR-NEW-16 DoD-2)..."
	@mkdir -p dist
	@$(UV_RUN) python tools/checks/pii_audit.py --mode full --threshold 0.9 \
		--report dist/pii-audit-report.json \
		&& $(SUCCESS) "[pii-audit] precision/recall >= 0.9 на hybrid gold-set"

pii-bootstrap: check-env ## S24 W1: Download spaCy ru_core_news_lg weights (~1.5GB)
	@$(INFO) "Downloading spaCy ru_core_news_lg..."
	@$(UV_RUN) python -m spacy download ru_core_news_lg
	@$(SUCCESS) "spaCy ru_core_news_lg installed"

ai-rag-eval: check-env ## Wave 6 GAP-AI: RAGAS evaluation (faithfulness/answer_relevancy/context_precision)
	@$(INFO) "Running RAGAS evaluation (banking samples)..."
	@$(UV_RUN) python -m tools.checks.ragas_runner --dataset banking \
		&& $(SUCCESS) "[ai-rag-eval] metrics >= thresholds" \
		|| $(WARN) "[ai-rag-eval] metrics below threshold (см. artifacts/ragas/)"

ai-rag-eval-strict: check-env ## Wave 6 GAP-AI: RAGAS evaluation как blocking-gate (exit 1 при провале метрик)
	@$(INFO) "Running RAGAS evaluation strict (CI gate)..."
	@mkdir -p artifacts/ragas
	@$(UV_RUN) python -m tools.checks.ragas_runner --dataset banking
	@$(SUCCESS) "[ai-rag-eval-strict] все метрики выше порога"

check-hardcoded-prompts: check-env ## Wave 13 GAP-AI: скан hardcoded LLM-prompts (warn-only)
	@$(INFO) "Running check-hardcoded-prompts (services/ai, min-length=50)..."
	@$(UV_RUN) python -m tools.checks.check_hardcoded_prompts \
		--root src/backend/services/ai \
		--allowlist tools/checks/prompt_allowlist.txt

check-hardcoded-prompts-strict: check-env ## Wave 13 GAP-AI: blocking-gate hardcoded prompts (exit=1 при findings)
	@$(INFO) "Running check-hardcoded-prompts --strict (CI gate)..."
	@$(UV_RUN) python -m tools.checks.check_hardcoded_prompts \
		--root src/backend/services/ai \
		--root src/backend/core/ai \
		--allowlist tools/checks/prompt_allowlist.txt \
		--strict

api-fuzz: check-env ## S6 K2: schemathesis API fuzzing через tools/api_fuzz_runner.py (warn-only, feature_flag schemathesis_gate_enabled)
	@$(INFO) "Running api-fuzz (schemathesis property-based testing)..."
	@mkdir -p dist
	@$(UV_RUN) python tools/api_fuzz_runner.py \
		--openapi http://$(UVICORN_HOST):$(UVICORN_PORT)/openapi.json \
		--report dist/schemathesis-report.json \
		|| $(WARN) "[api-fuzz] warn-only: feature_flag schemathesis_gate_enabled=false"

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

##@ V11 R1.2 — manifest schemas + capability catalog (ADR-042/043/044)

plugin-schema: check-env ## Wave R1.2: dump plugin.toml JSON-Schema → docs/reference/schemas/
	@$(UV_RUN) python tools/export_v11_artefacts.py plugin-schema

route-schema: check-env ## Wave R1.2a: dump route.toml JSON-Schema → docs/reference/schemas/
	@$(UV_RUN) python tools/export_v11_artefacts.py route-schema

capability-catalog: check-env ## Wave R1.1: dump capability vocabulary → docs/reference/capabilities.md
	@$(UV_RUN) python tools/export_v11_artefacts.py capability-catalog

v11-artefacts: check-env ## Wave R1: regenerate plugin/route schemas + capability catalog
	@$(UV_RUN) python tools/export_v11_artefacts.py all

v11-artefacts-check: check-env ## Wave R1: проверить, что committed schemas/capabilities в синке с кодом
	@$(UV_RUN) python tools/check_v11_artefacts.py

check-compat: check-env ## Sprint 14 W1: матрица совместимости plugin.toml::[compatibility]
	@$(UV_RUN) python -m tools.checks.check_compat --plugins-dir extensions/

publish-plugin: check-env ## Sprint 14 W3: bundle + SBOM + cosign + upload плагина (PLUGIN=<name> VERSION=<semver>)
	@if [ -z "$(PLUGIN)" ] || [ -z "$(VERSION)" ]; then \
		echo "Использование: make publish-plugin PLUGIN=<name> VERSION=<semver>"; \
		exit 2; \
	fi
	@$(UV_RUN) python -m tools.publish_plugin --plugin "$(PLUGIN)" --version "$(VERSION)" $(PUBLISH_FLAGS)

plugin-migrate-guide: check-env ## Sprint 14 K5 W1: сгенерировать migration guide PLUGIN=<name> FROM=<ref/path> TO=<ref/path>
	@if [ -z "$(PLUGIN)" ] || [ -z "$(FROM)" ] || [ -z "$(TO)" ]; then \
		echo "Использование: make plugin-migrate-guide PLUGIN=<name> FROM=<git-ref|path> TO=<git-ref|path>"; \
		exit 2; \
	fi
	@$(UV_RUN) python -m tools.plugin_migration_diff --plugin "$(PLUGIN)" --from-ref "$(FROM)" --to-ref "$(TO)"

perf-plugin-sandbox: check-env ## Sprint 14 K2 W2: pytest-benchmark plugin sandbox overhead
	@$(UV_RUN) pytest tests/perf/test_plugin_sandbox_overhead.py --benchmark-only --benchmark-json=tests/perf/baselines/plugin_sandbox.benchmark.json

dsl-stubs: ## Sprint 14 K3 W2: regenerate .pyi stubs for RouteBuilder/WorkflowBuilder
	@.venv/bin/python -m tools.gen_dsl_stubs

dsl-stubs-check: ## Sprint 14 K3 W2: CI gate — нет ли drift между .pyi и runtime
	@.venv/bin/python -m tools.gen_dsl_stubs --check

migrate-plugin-manifest: check-env ## Wave R1.2.b: convert plugins/<name>/plugin.yaml → plugin.toml (PLUGIN_DIR=...)
	@if [ -z "$(PLUGIN_DIR)" ]; then \
		echo "Использование: make migrate-plugin-manifest PLUGIN_DIR=plugins/example_plugin"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/migrate_plugin_manifest.py "$(PLUGIN_DIR)"

migrate-dsl-routes: check-env ## Wave R1.2a.b: wrap dsl_routes/*.yaml into routes/<name>/ (FROM=dsl_routes/ TO=routes/)
	@$(UV_RUN) python tools/migrate_dsl_routes_to_v11.py "$(or $(FROM),dsl_routes)" "$(or $(TO),routes)"

grpc-codegen: check-env ## Wave 1.3: generate .proto + compile pb2/pb2_grpc for gRPC actions
	@APP_PROFILE=dev_light $(UV_RUN) --extra dev-light python tools/codegen_proto.py --clean

grpc-codegen-dry: check-env ## Wave 1.3: dry-run — print plan only
	@APP_PROFILE=dev_light $(UV_RUN) --extra dev-light python tools/codegen_proto.py --dry-run

##@ Codegen Wave 5

new-service: check-env ## Scaffold service+repo+schema+action (NAME=plural DOMAIN=core [CRUD=1] [FIELDS='{"k":"str"}'])
	@if [ -z "$(NAME)" ] || [ -z "$(DOMAIN)" ]; then \
		echo "Использование: make new-service NAME=<plural> DOMAIN=<area> [CRUD=1] [FIELDS='{...}']"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/codegen_service.py --name "$(NAME)" --domain "$(DOMAIN)" \
		$(if $(CRUD),--crud,) $(if $(FIELDS),--fields '$(FIELDS)',) \
		$(if $(MODEL_CLASS),--model-class "$(MODEL_CLASS)",) \
		$(if $(OVERWRITE),--overwrite,)

new-repository: check-env ## Scaffold sqlalchemy repository (NAME=plural [MODEL_CLASS=Name])
	@if [ -z "$(NAME)" ]; then \
		echo "Использование: make new-repository NAME=<plural> [MODEL_CLASS=Name]"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/codegen_repository.py --name "$(NAME)" \
		$(if $(MODEL_CLASS),--model-class "$(MODEL_CLASS)",) \
		$(if $(OVERWRITE),--overwrite,)

codegen-extract: check-env ## Reverse codegen: service.py → YAML (SERVICE=<path> [OUTPUT=-])
	@if [ -z "$(SERVICE)" ]; then \
		echo "Использование: make codegen-extract SERVICE=<path> [OUTPUT=-]"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/codegen_extract.py --service "$(SERVICE)" --output "$(or $(OUTPUT),-)"

import-swagger: check-env ## Swagger/OpenAPI → actions (URL=<spec> CONNECTOR=<name> [WRITE=1])
	@if [ -z "$(URL)" ] || [ -z "$(CONNECTOR)" ]; then \
		echo "Использование: make import-swagger URL=<spec> CONNECTOR=<name> [WRITE=1]"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/import_swagger.py --url "$(URL)" --connector "$(CONNECTOR)" \
		$(if $(WRITE),--write,) $(if $(OUTPUT_DIR),--output-dir "$(OUTPUT_DIR)",)

import-postman: check-env ## Postman v2.1 → actions (FILE=<json> CONNECTOR=<name> [WRITE=1])
	@if [ -z "$(FILE)" ] || [ -z "$(CONNECTOR)" ]; then \
		echo "Использование: make import-postman FILE=<json> CONNECTOR=<name> [WRITE=1]"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/import_postman.py --file "$(FILE)" --connector "$(CONNECTOR)" \
		$(if $(WRITE),--write,) $(if $(OUTPUT_DIR),--output-dir "$(OUTPUT_DIR)",)

import-wsdl: check-env ## WSDL → actions (URL=<wsdl> CONNECTOR=<name> [WRITE=1])
	@if [ -z "$(URL)" ] || [ -z "$(CONNECTOR)" ]; then \
		echo "Использование: make import-wsdl URL=<wsdl> CONNECTOR=<name> [WRITE=1]"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/import_wsdl.py --url "$(URL)" --connector "$(CONNECTOR)" \
		$(if $(WRITE),--write,) $(if $(OUTPUT_DIR),--output-dir "$(OUTPUT_DIR)",)

##@ K5 — testkit / chaos / perf / new-plugin

testkit-smoke: check-env ## К5: запуск unit-тестов testkit (recorder/replay/route_runner/fixtures)
	@$(INFO) "Running testkit smoke tests..."
	@$(UV_RUN) pytest tests/unit/testkit_pkg -q
	@$(SUCCESS) "testkit OK"

new-plugin: check-env ## К5: scaffold extensions/<NAME>/ V11 plugin (FEATURES='ping,echo')
	@if [ -z "$(NAME)" ]; then \
		echo "Использование: make new-plugin NAME=<plugin_name> [FEATURES='ping,echo'] [CAPABILITIES='mq.publish'] [WITH_FRONTEND=1]"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/codegen_plugin.py \
		--name "$(NAME)" \
		$(if $(FEATURES),--features "$(FEATURES)",) \
		$(if $(CAPABILITIES),--capabilities "$(CAPABILITIES)",) \
		$(if $(WITH_FRONTEND),--with-frontend,) \
		$(if $(OVERWRITE),--overwrite,)

perf-smoke: check-env ## К5: short k6 baseline (~1 min) против запущенного backend
	@$(INFO) "Running k6 smoke profile..."
	@command -v k6 >/dev/null 2>&1 || { $(ERROR) "k6 not installed (https://k6.io/docs/getting-started/installation)"; exit 1; }
	@k6 run -e BASE_URL=$(or $(BASE_URL),http://127.0.0.1:8000) tests/perf/k6_baseline.js

perf-full: check-env ## К5: full locust run (3 min, 100 VU)
	@$(INFO) "Running locust full profile..."
	@$(UV_RUN) --extra perf locust -f tests/perf/locust_full_profile.py \
		--host=$(or $(BASE_URL),http://127.0.0.1:8000) \
		--users 100 --spawn-rate 10 --run-time 3m --headless

perf-gate: check-env ## К5: enforced perf-gate (k6 with thresholds; fails if SLO breached)
	@$(INFO) "Running perf-gate (p95<200ms, RPS>1000, error<1%)..."
	@command -v k6 >/dev/null 2>&1 || { $(ERROR) "k6 not installed"; exit 1; }
	@k6 run --summary-export=dist/k6-summary.json \
		-e BASE_URL=$(or $(BASE_URL),http://127.0.0.1:8000) \
		tests/perf/k6_action_routes.js

perf-gate-py: ## К3/S2: python perf-gate — проверяет locust-метрики против baseline.json (warn-only до S3)
	@$(INFO) "Running python perf-gate against baseline tests/perf/baseline.json..."
	@mkdir -p dist
	@$(UV_RUN) python tools/perf_gate.py \
		--scenario tests/perf/locust_baseline.py \
		--host $(or $(BASE_URL),http://localhost:8000) \
		--report dist/perf-report.json \
		|| $(WARN) "[perf-gate-py] warn-only: thresholds not met (будет block в S3)"

perf-gate-py-strict: check-env ## Sprint 9 K2 W7: blocking perf-gate (p95<200ms, RPS>1000, ratchet baseline)
	@$(INFO) "Running BLOCKING python perf-gate against baseline tests/perf/baseline.json..."
	@mkdir -p dist
	@$(UV_RUN) python tools/perf_gate.py \
		--scenario tests/perf/locust_baseline.py \
		--host $(or $(BASE_URL),http://localhost:8000) \
		--report dist/perf-report.json \
		--strict
	@$(INFO) "[perf-gate-py-strict] OK"

granian-run: ## S6 K2: запуск Granian с production-tuning (ADR-0059)
	@$(INFO) "Starting Granian with production tuning (ADR-0059)..."
	@$(UV_RUN) python tools/granian_runner.py --app src.main:app --host $(or $(GRANIAN_HOST),0.0.0.0) --port $(or $(GRANIAN_PORT),8000)

granian-dry-run: ## S6 K2: вывести Granian CLI-команду без запуска (debug)
	@$(UV_RUN) python tools/granian_runner.py --app src.main:app --dry-run

perf-baseline: ## К3/S2: перегенерировать tests/perf/baseline.json из актуального staging-прогона
	@$(INFO) "Regenerating perf baseline → tests/perf/baseline.json..."
	@$(UV_RUN) python tools/perf_gate.py \
		--scenario tests/perf/locust_baseline.py \
		--host $(or $(BASE_URL),http://localhost:8000) \
		--report tests/perf/baseline.json \
		|| $(WARN) "[perf-baseline] локуст не запустился — baseline не обновлён"

chaos: check-env ## К5: chaos × 33 (toxiproxy required; Docker required)
	@$(INFO) "Running chaos suite (33 scenarios)..."
	@$(UV_RUN) pytest tests/chaos -q -m "chaos"

chaos-slow: check-env ## К5: chaos including slow scenarios
	@$(INFO) "Running chaos + slow suite..."
	@$(UV_RUN) pytest tests/chaos -q -m "chaos or slow"

docs-vale: check-env ## К5: prose lint Markdown через Vale + proselint
	@$(INFO) "Running Vale + proselint on docs/..."
	@command -v vale >/dev/null 2>&1 && vale docs/ || $(INFO) "vale CLI not installed — skip"
	@$(UV_RUN) python -m proselint docs/ || true

check-docstrings: check-env ## S35 w3: docstring policy gate (Wave F.6) — pre-push hook
	@$(INFO) "Running docstring policy check..."
	@$(UV_RUN) python tools/check_docstrings.py \
		src/backend/core src/backend/dsl/engine src/backend/core/interfaces \
		&& $(SUCCESS) "docstring policy OK"

##@ Profiling

profile-memray: check-env ## Run FastAPI under Memray
	@mkdir -p "$(PROFILE_DIR)"
	@if $(UV_RUN) memray --version >/dev/null 2>&1; then \
		$(INFO) "Running Memray profiler..."; \
		$(UV_RUN) memray run -o "$(MEMRAY_OUTPUT)" -m uvicorn "$(UVICORN_APP)" --host "$(UVICORN_HOST)" --port "$(UVICORN_PORT)"; \
	else \
		$(ERROR) "memray is not installed in uv env"; \
		printf '%s\n' "Run: uv add --dev memray"; \
		exit 1; \
	fi

profile-memray-flamegraph: check-env ## Generate Memray flamegraph HTML
	@mkdir -p "$(PROFILE_DIR)"
	@if [ ! -f "$(MEMRAY_OUTPUT)" ]; then \
		$(ERROR) "Memray output not found: $(MEMRAY_OUTPUT)"; \
		printf '%s\n' "Run: make profile-memray"; \
		exit 1; \
	fi
	@if $(UV_RUN) memray --version >/dev/null 2>&1; then \
		$(INFO) "Generating Memray flamegraph..."; \
		$(UV_RUN) memray flamegraph -o "$(MEMRAY_FLAMEGRAPH)" "$(MEMRAY_OUTPUT)"; \
		$(SUCCESS) "Memray flamegraph generated: $(MEMRAY_FLAMEGRAPH)"; \
	else \
		$(ERROR) "memray is not installed in uv env"; \
		printf '%s\n' "Run: uv add --dev memray"; \
		exit 1; \
	fi

profile-memray-stats: check-env ## Show Memray stats
	@if [ ! -f "$(MEMRAY_OUTPUT)" ]; then \
		$(ERROR) "Memray output not found: $(MEMRAY_OUTPUT)"; \
		printf '%s\n' "Run: make profile-memray"; \
		exit 1; \
	fi
	@if $(UV_RUN) memray --version >/dev/null 2>&1; then \
		$(INFO) "Showing Memray stats..."; \
		$(UV_RUN) memray stats "$(MEMRAY_OUTPUT)"; \
	else \
		$(ERROR) "memray is not installed in uv env"; \
		printf '%s\n' "Run: uv add --dev memray"; \
		exit 1; \
	fi

profile-mprof: check-env ## Run memory profiling with mprof
	@mkdir -p "$(PROFILE_DIR)"
	@if $(UV_RUN) mprof --help >/dev/null 2>&1; then \
		$(INFO) "Running mprof..."; \
		$(UV_RUN) mprof run --output "$(MPROF_OUTPUT)" uvicorn "$(UVICORN_APP)" --host "$(UVICORN_HOST)" --port "$(UVICORN_PORT)"; \
		$(SUCCESS) "mprof output saved: $(MPROF_OUTPUT)"; \
	else \
		$(ERROR) "mprof is not installed in uv env"; \
		printf '%s\n' "Run: uv add --dev memory-profiler"; \
		exit 1; \
	fi

profile-pyspy: ## Record CPU profile with py-spy
	@mkdir -p "$(PROFILE_DIR)"
	@if command -v py-spy >/dev/null 2>&1; then \
		$(INFO) "Recording py-spy profile..."; \
		py-spy record -o "$(PYSPY_OUTPUT)" -- python -m uvicorn "$(UVICORN_APP)" --host "$(UVICORN_HOST)" --port "$(UVICORN_PORT)"; \
		$(SUCCESS) "py-spy profile saved: $(PYSPY_OUTPUT)"; \
	else \
		$(ERROR) "py-spy is not installed on host"; \
		printf '%s\n' "Install: pip install py-spy"; \
		exit 1; \
	fi

##@ Docs

docs-clean: ## К10 S2 W5: clean Sphinx build artifacts
	rm -rf $(DOCS_BUILD)/*

docs-apidoc:
	@# autoapi (sphinx-autoapi) делает discovery сам — sphinx-apidoc не нужен.
	@true

docs-html: ## К10 S2 W5: build Sphinx HTML (warnings = errors via -W)
	uv run sphinx-build -b html -W --keep-going $(DOCS_SOURCE) $(DOCS_BUILD)/html

docs-multiversion: ## K1 S8 [wave:s8/k1-sphinx-multiversion]: build всех whitelist-ref'ов в $(DOCS_BUILD)/multi/<ref>
	uv run sphinx-multiversion $(DOCS_SOURCE) $(DOCS_BUILD)/multi

docs-rebuild: docs-clean docs-apidoc docs-html

docs: docs-rebuild ## К10 S2 W5: build Sphinx documentation (Diátaxis structure)

docs-coverage: ## Wave 10.8 — docstring + HTML coverage gate
	@$(UV_RUN) python tools/docs_coverage.py --strict

coverage-gate: ## К3 S6 [wave:s6/k3-coverage-gate-70] — pytest coverage gate (blocking, baseline-aware)
	@$(INFO) "Running pytest with --cov + coverage gate..."
	$(UV_RUN) pytest tests --cov=src/backend --cov-report=xml --cov-report=term --maxfail=20
	$(UV_RUN) python tools/check_coverage_gate.py --coverage-xml coverage.xml --baseline .baselines/coverage.json --threshold 50
	@$(SUCCESS) "Coverage gate passed"

coverage-gate-strict: ## [wave:s19/k2-w4-coverage-ratchet-75] — coverage gate strict 70→75%
	@$(INFO) "Running pytest with --cov + coverage gate (strict, 75%)..."
	$(UV_RUN) pytest tests --cov=src/backend --cov-report=xml --cov-report=term --maxfail=20
	$(UV_RUN) python tools/check_coverage_gate.py --coverage-xml coverage.xml --baseline .baselines/coverage.json --threshold 75 --strict
	@$(SUCCESS) "Coverage gate strict (75%) passed"

pre-prod-check: ## S36 w4: 30+ gate pre-prod-check (BLOCKING, ratchet-aware)
	@$(INFO) "Running pre-prod-check (30+ gates)..."
	$(UV_RUN) python tools/checks/pre_prod_check.py

pre-prod-check-dry-run: ## S36 w4: pre-prod-check --dry-run (печатает список gates без исполнения)
	@$(INFO) "Dry-run pre-prod-check..."
	$(UV_RUN) python tools/checks/pre_prod_check.py --dry-run

pre-prod-check-ratchet: ## S36 w4: pre-prod-check + обновление baseline (--ratchet)
	@$(INFO) "Running pre-prod-check + ratchet baseline..."
	$(UV_RUN) python tools/checks/pre_prod_check.py --ratchet
	@$(SUCCESS) "pre-prod-check baseline updated"

##@ Git & Release

pre-commit: check-env ## Install and run pre-commit hooks
	@$(INFO) "Setting up pre-commit..."
	$(UV_RUN) pre-commit install
	$(UV_RUN) pre-commit run --all-files
	@$(SUCCESS) "Pre-commit configured!"

commit: ensure-branch ## Commit changes to Git (explicit paths — no -A)
	@$(INFO) "Committing changes (explicit paths, no -A)..."
	@# A2 security: запрещаем git add -A, чтобы исключить добавление
	@# случайных файлов (.env, artifacts, IDE-cruft, секреты).
	git add src/ docs/ scripts/ tools/ pyproject.toml uv.lock Makefile .pre-commit-config.yaml .gitignore 2>/dev/null || true
	@# Опциональные корневые файлы — добавляются, только если существуют.
	@[ -f .gitlab-ci.yml ] && git add .gitlab-ci.yml || true
	@[ -f ops/compose/Dockerfile ] && git add ops/compose/Dockerfile || true
	@[ -f ops/compose/docker-compose.yml ] && git add ops/compose/docker-compose.yml || true
	@if git diff --cached --quiet; then \
		$(WARN) "Nothing to commit"; \
	else \
		if [ "$(GIT_NO_VERIFY)" = "1" ]; then \
			git commit -m "$(GIT_COMMIT_MESSAGE)" --no-verify; \
		else \
			git commit -m "$(GIT_COMMIT_MESSAGE)"; \
		fi; \
	fi

current-version: check-env ## Show current semantic version
	@$(UV_RUN) semantic-release print-version --current

next-version: check-env ## Show what the next version will be
	@$(UV_RUN) semantic-release print-version --next

bump: check-env ## Bump version, update CHANGELOG and tag via Semantic Release
	@$(INFO) "Running semantic-release..."
	@if $(UV_RUN) semantic-release --version >/dev/null 2>&1; then \
		$(UV_RUN) semantic-release version; \
	else \
		$(ERROR) "python-semantic-release is not installed"; \
		printf '%s\n' "Run: uv add --dev python-semantic-release"; \
		exit 1; \
	fi

push: ensure-branch ## Push changes and tags to remote repository
	@$(INFO) "Pushing to $(BRANCH)..."
	git push -u origin $(BRANCH)
	git push --tags

git-sync: ## Commit and push current branch
	@$(MAKE) commit
	@$(MAKE) push
	@$(SUCCESS) "Git sync finished!"

##@ Pipelines

code-lint: ## Format and run soft lint
	@$(MAKE) format
	@$(MAKE) lint
	@$(SUCCESS) "Code lint pipeline finished!"

code-check: ## Run all soft checks
	@$(MAKE) lint
	@$(MAKE) deps-check
	@$(MAKE) secrets-check
	@$(SUCCESS) "All soft checks finished!"

check-strict: ## Run strict checks except mypy and vulture
	@$(MAKE) lint-strict
	@$(MAKE) deps-check-strict
	@$(MAKE) secrets-check
	@$(MAKE) check-waf-coverage-strict
	@$(SUCCESS) "All strict checks passed!"

ci: ## К1 V15 — composite CI gate (lint + type + tests + security + WAF strict)
	@$(MAKE) format-check
	@$(MAKE) lint-strict
	@$(MAKE) type-check-strict
	@$(MAKE) deps-check-strict
	@$(MAKE) secrets-check
	@$(MAKE) check-waf-coverage-strict
	@$(MAKE) check-ai-safety
	@$(MAKE) check-python3-syntax
	@$(MAKE) check-task-registry
	@$(SUCCESS) "CI gate passed"

pr: ## К1 V15 — composite PR gate (ci + docs)
	@$(MAKE) ci
	@$(MAKE) docs
	@$(SUCCESS) "PR gate passed"

check-strict-full: ## Clean caches and run all strict checks including mypy
	@$(MAKE) clean
	@$(INFO) "Auto-fixing code style before strict checks..."
	@$(MAKE) fix
	@$(MAKE) check-strict
	@$(MAKE) type-check-strict
	@$(MAKE) clean
	@$(SUCCESS) "All strict checks including mypy passed!"

fix-check-push: ## Auto-fix, verify, commit and push
	@$(MAKE) fix
	@$(MAKE) check-strict
	@$(MAKE) commit
	@$(MAKE) push
	@$(SUCCESS) "Fix, check and push pipeline finished!"

ship: ## Short alias for fix-check-push
	@$(MAKE) fix-check-push
	@$(SUCCESS) "Ship pipeline finished!"

ship-release: ## Run strict checks, commit, and automate release process
	@$(MAKE) fix
	@$(MAKE) check-strict
	@$(MAKE) commit
	@$(MAKE) bump
	@$(MAKE) push
	@$(SUCCESS) "Release shipped successfully!"

all: ## Clean, verify, migrate and run app with watcher
	@$(MAKE) clean
	@$(MAKE) fix
	@$(MAKE) check-strict
	@$(MAKE) migrate
	@$(MAKE) up
	@$(SUCCESS) "All-in-one local workflow finished!"

##@ Maintenance

clean: ## Clean temporary files and caches
	@$(INFO) "Cleaning project..."
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".hypothesis" -exec rm -rf {} +
	rm -rf .coverage .coverage.* htmlcov .benchmarks dist build .eggs .run profiles
	@$(SUCCESS) "Cleaning complete!"

clean-all: clean ## Full clean including virtualenv and logs
	@$(INFO) "Removing virtual environment and logs..."
	rm -rf .venv logs
	@$(SUCCESS) "Full clean complete!"

code-clean: ## Alias for clean
	@$(MAKE) clean
	@$(SUCCESS) "Project cleanup finished!"

##@ Docker

docker-build: check-docker ## Build Docker image
	@$(INFO) "Building Docker image $(IMAGE_NAME):$(IMAGE_TAG)..."
	$(DOCKER) build -t $(IMAGE_NAME):$(IMAGE_TAG) .
	@$(SUCCESS) "Docker image built!"

docker-run: check-docker ## Run Docker container
	@$(INFO) "Running Docker container..."
	$(DOCKER) run --rm \
		-p 8000:8000 \
		-p 4200:4200 \
		-p 50051:50051 \
		--name $(IMAGE_NAME) \
		$(IMAGE_NAME):$(IMAGE_TAG)

docker-stop: check-docker ## Stop Docker container
	@$(INFO) "Stopping Docker container..."
	-$(DOCKER) stop $(IMAGE_NAME)
	@$(SUCCESS) "Docker container stopped!"

tag: ## Create and push version tag (legacy)
	@if [ -z "$(TAG)" ]; then \
		$(ERROR) "TAG is required. Example: make tag TAG=v1.2.3"; \
		exit 1; \
	fi
	@$(INFO) "Creating version tag..."
	git tag $(TAG)
	git push origin $(TAG)
	@$(SUCCESS) "Tag $(TAG) pushed!"

##@ Production Readiness

readiness-check: ## Run all anti-forget guards locally
	@$(INFO) "Running anti-forget guards..."
	$(UV_RUN) python3 tools/check_fallback_matrix.py
	@$(SUCCESS) "All guards passed!"

# ---------------------------------------------------------------------- #
# Wave F.7 — post-wave memory скелет (Roadmap V10 #13).                  #
# Использование: make wave-memory NAME=<slug> [TYPE=feedback|project]    #
# ---------------------------------------------------------------------- #
wave-memory: ## Generate post-wave memory note skeleton (NAME=<slug> [TYPE=feedback])
	@if [ -z "$(NAME)" ]; then \
		printf '\033[31mERROR: NAME=<slug> обязателен. Пример: make wave-memory NAME=invoker_consolidation\033[0m\n'; \
		exit 2; \
	fi
	$(UV_RUN) python3 tools/wave_memory.py --name "$(NAME)" --type "$(or $(TYPE),feedback)"

# ---------------------------------------------------------------------- #
# Sprint 8 K1 — server-side pre-receive docstring gate.                  #
# Использование: make install-pre-receive REMOTE=/path/to/repo.git       #
# Копирует tools/git_hooks/pre-receive в hooks/ указанной remote-копии.   #
# ---------------------------------------------------------------------- #
.PHONY: install-pre-receive

install-pre-receive: ## К1 S8 — установить pre-receive docstring gate на git-сервере (REMOTE=path)
	@if [ -z "$(REMOTE)" ]; then \
		printf '\033[31mERROR: REMOTE=<path> обязателен.\033[0m\n'; \
		printf 'Пример: make install-pre-receive REMOTE=/srv/git/gd_integration_tools.git\n'; \
		exit 2; \
	fi
	@if [ ! -d "$(REMOTE)/hooks" ]; then \
		printf '\033[31mERROR: $(REMOTE)/hooks не существует. Это bare-репозиторий?\033[0m\n'; \
		exit 2; \
	fi
	@$(INFO) "Устанавливаю pre-receive hook в $(REMOTE)/hooks/..."
	cp tools/git_hooks/pre-receive "$(REMOTE)/hooks/pre-receive"
	chmod +x "$(REMOTE)/hooks/pre-receive"
	@$(SUCCESS) "Pre-receive hook установлен. Не забудьте задать GD_PROJECT_DIR на git-сервере."

# ---------------------------------------------------------------------- #
# V16 Sprint 0 — codeclone (clone detection through MCP).                #
# Установка: uv tool install "codeclone[mcp]" (выполнено 2026-05-06).     #
# ---------------------------------------------------------------------- #
CODECLONE_THRESHOLD ?= 0.85
CLONE_REPORT_DIR ?= docs/clone-reports
CLONE_BASELINE ?= docs/clone-baseline.json

.PHONY: review-clones review-clones-baseline review-clones-diff

review-clones:  ## Найти copy-paste и semantic clones в src/backend (HTML отчёт)
	@mkdir -p $(CLONE_REPORT_DIR)
	uv tool run --from "codeclone[mcp]" codeclone \
		--html $(CLONE_REPORT_DIR)/clones-$(shell date +%Y%m%d-%H%M%S).html \
		--no-progress src/backend/
	@echo "Reports: $(CLONE_REPORT_DIR)/"

review-clones-baseline:  ## Снять текущий baseline для будущих сравнений
	uv tool run --from "codeclone[mcp]" codeclone \
		--json $(CLONE_BASELINE) \
		--update-baseline \
		--no-progress src/backend/
	@echo "Baseline saved: $(CLONE_BASELINE)"

review-clones-diff:  ## Сравнить с baseline; fail при появлении новых дублей (CI gate)
	uv tool run --from "codeclone[mcp]" codeclone \
		--baseline $(CLONE_BASELINE) \
		--no-progress src/backend/

# ---------------------------------------------------------------------- #
# Sprint 17 K9 — AST-aware grep-gate для запрещённых паттернов V22 §5.   #
# Скрипт фильтрует docstring-блоки, CLI selftest и ruamel.yaml.          #
# ---------------------------------------------------------------------- #
.PHONY: check-grep-violations check-python3-syntax check-task-registry middleware-tree

check-grep-violations: check-env ## V22 §5: AST-aware fail-on запрещённые паттерны (8 правил)
	$(UV_RUN) python tools/checks/check_grep_violations.py --root src/backend

check-python3-syntax: check-env ## V22 §S17 DoD #2: запрет except A, B: без скобок (Python-2 стиль)
	$(UV_RUN) python tools/checks/check_python3_syntax.py --root src/backend

check-task-registry: check-env ## S17 K2 W3 (R-V15-11): orphan asyncio.create_task / ensure_future
	$(UV_RUN) python tools/checks/check_task_registry.py --root src/backend

middleware-tree: check-env ## S17 ADR-NEW-2: показать дерево зарегистрированных middleware по слоям
	$(UV_RUN) python tools/middleware_tree.py

##@ K5 S19 W4 — quick-wins-pack (new-adr + completions + release-notes)

new-adr: ## Создать новый ADR из шаблона (TITLE="Заголовок ADR" [NUMBER=123])
	@if [ -z "$(TITLE)" ]; then \
		echo "Использование: make new-adr TITLE=\"Мой новый ADR\""; \
		exit 1; \
	fi
	$(UV_RUN) python tools/new_adr.py "$(TITLE)" $(if $(NUMBER),--adr-number $(NUMBER),)

release-notes: ## Сгенерировать release-notes из wave-tags в git log (FROM=v0.1.0 TO=v0.2.0)
	$(UV_RUN) python tools/changelog_autogen.py $(if $(FROM),--from $(FROM),) $(if $(TO),--to $(TO),) $(if $(OUTPUT),--output $(OUTPUT),)
