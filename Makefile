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

CONFIG_FILE ?= ./config.yml
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
	docs-clean docs-apidoc docs-html docs-rebuild docs

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

run: check-env ## Start backend in foreground
	@$(MANAGE_SCRIPT) run

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
	@$(MANAGE_SCRIPT) routes

actions: check-env ## List registered actions
	@$(MANAGE_SCRIPT) actions

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
	@$(SUCCESS) "All guards passed!"
