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
DOCS_SOURCE := $(DOCS_DIR)/source
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

UVICORN_APP ?= src.main:app
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

.PHONY: \
	help \
	init install update lock \
	check-env check-script check-docker ensure-branch \
	format format-check fix \
	lint lint-strict \
	type-check type-check-strict \
	vulture-check refurb-check \
	clean clean-all code-clean \
	run run-fg stop restart status migrate rabbit-init \
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
	import-swagger import-postman import-wsdl

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

api-fuzz: check-env ## Run property-based testing against live FastAPI
	@$(INFO) "Running Schemathesis API tests..."
	@if $(UV_RUN) schemathesis --version >/dev/null 2>&1; then \
		$(UV_RUN) schemathesis run http://$(UVICORN_HOST):$(UVICORN_PORT)/openapi.json \
			--checks all; \
	else \
		$(WARN) "Skipping schemathesis: install it with 'uv add --dev schemathesis'"; \
	fi

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

scaffold: check-env ## Scaffold new component (usage: make scaffold type=service name=invoices)
	@$(MANAGE_SCRIPT) scaffold $(type) $(name)

routes: check-env ## List DSL routes
	@APP_PROFILE=dev_light $(MANAGE_LIGHT) routes

actions: check-env ## List registered actions
	@APP_PROFILE=dev_light $(MANAGE_LIGHT) actions

actions-strict: check-env ## Wave B: list actions + fail on inferred action_id
	@APP_PROFILE=dev_light $(MANAGE_LIGHT) actions --strict

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

docs-clean:
	rm -rf $(DOCS_BUILD)/*

docs-apidoc:
	uv run sphinx-apidoc -f -o $(DOCS_SOURCE) $(APP_DIR)

docs-html:
	uv run sphinx-build -b html $(DOCS_SOURCE) $(DOCS_BUILD)/html

docs-rebuild: docs-clean docs-apidoc docs-html

docs: docs-rebuild

docs-coverage: ## Wave 10.8 — docstring + HTML coverage gate
	@$(UV_RUN) python tools/docs_coverage.py --strict

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
	@[ -f Dockerfile ] && git add Dockerfile || true
	@[ -f docker-compose.yml ] && git add docker-compose.yml || true
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
	@$(SUCCESS) "All strict checks passed!"

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

phase-audit: ## Audit phase readiness. Usage: make phase-audit PHASE=A1
	@if [ -z "$(PHASE)" ]; then \
		$(ERROR) "PHASE is required. Example: make phase-audit PHASE=A1"; \
		exit 1; \
	fi
	@bash scripts/audit.sh $(PHASE)

progress: ## Show phase progress summary
	@$(UV_RUN) python3 tools/report_phases.py

phases: ## Show only in-progress phases
	@$(UV_RUN) python3 tools/report_phases.py --only in-progress

mr-description: ## Render MR description from PROGRESS + STATUS
	@$(UV_RUN) python3 tools/render_mr_description.py

readiness-check: ## Run all anti-forget guards locally
	@$(INFO) "Running anti-forget guards..."
	$(UV_RUN) python3 tools/check_phase_order.py
	$(UV_RUN) python3 tools/check_deps_matrix.py
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
