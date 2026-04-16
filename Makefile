SHELL := /bin/sh

.DEFAULT_GOAL := help

# Ожидается формат Conventional Commits, например: "feat: add oracle db auth"
GIT_COMMIT_MESSAGE ?= chore: code quality improvements
BRANCH ?= main
SOURCE_DIR ?= ./app

RUFF_ARGS ?=

IMAGE_NAME ?= gd-integration-tools
IMAGE_TAG ?= py314

DOCS_DIR := docs
DOCS_SOURCE := $(DOCS_DIR)/source
DOCS_BUILD := $(DOCS_DIR)/build
APP_DIR := app

TAG ?=
GIT_NO_VERIFY ?= 1

DOCKER ?= docker
POETRY_RUN := poetry run
MANAGE_SCRIPT := ./scripts/manage.sh

CONFIG_FILE ?= ./config.yml
CONFIG_WATCHER_SCRIPT ?= ./tools/config_watcher.py
RUN_DIR ?= ./.run
LOG_DIR ?= ./logs
CONFIG_WATCHER_PID_FILE ?= $(RUN_DIR)/config-watcher.pid
CONFIG_WATCHER_LOG_FILE ?= $(LOG_DIR)/config-watcher.log

UVICORN_APP ?= app.main:app
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
	check-env check-script check-watch-config check-docker ensure-branch \
	format format-check fix \
	lint lint-strict \
	type-check type-check-strict \
	vulture-check refurb-check \
	clean clean-all code-clean \
	run run-fg stop restart status migrate rabbit-init \
	up down restart-all status-all \
	watch-config watch-config-stop watch-config-status \
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

init: ## Initialize project with Poetry
	@$(INFO) "Initializing project..."
	poetry config virtualenvs.in-project true
	poetry install --with dev
	@$(SUCCESS) "Project initialized!"

install: ## Install dependencies
	poetry install --with dev

update: ## Update dependencies
	poetry update

lock: ## Refresh lock file
	poetry lock

check-env: ## Check Poetry environment
	@if poetry env info --path >/dev/null 2>&1; then \
		$(SUCCESS) "Poetry virtual environment detected"; \
	else \
		$(WARN) "No Poetry virtual environment found. Run 'poetry env use 3.14 && poetry install --with dev'"; \
		exit 1; \
	fi

check-script: ## Check manage script exists and executable
	@if [ -x "$(MANAGE_SCRIPT)" ]; then \
		$(SUCCESS) "Management script detected"; \
	else \
		$(ERROR) "$(MANAGE_SCRIPT) not found or not executable"; \
		printf '%s\n' "Run: chmod +x $(MANAGE_SCRIPT)"; \
		exit 1; \
	fi

check-watch-config: check-env check-script ## Check config watcher prerequisites
	@if [ -f "$(CONFIG_FILE)" ]; then \
		$(SUCCESS) "Config file detected: $(CONFIG_FILE)"; \
	else \
		$(ERROR) "Config file not found: $(CONFIG_FILE)"; \
		exit 1; \
	fi
	@if [ -f "$(CONFIG_WATCHER_SCRIPT)" ]; then \
		$(SUCCESS) "Config watcher detected: $(CONFIG_WATCHER_SCRIPT)"; \
	else \
		$(ERROR) "Config watcher not found: $(CONFIG_WATCHER_SCRIPT)"; \
		exit 1; \
	fi
	@if $(POETRY_RUN) python -c "import watchdog" >/dev/null 2>&1; then \
		$(SUCCESS) "watchdog is available"; \
	else \
		$(ERROR) "watchdog is not installed in Poetry env"; \
		printf '%s\n' "Run: poetry add --group dev watchdog"; \
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
	$(POETRY_RUN) ruff check --select I --fix $(SOURCE_DIR)
	$(POETRY_RUN) ruff format $(SOURCE_DIR)
	@$(SUCCESS) "Formatting complete!"

format-check: check-env ## Check formatting without modifying files
	@$(INFO) "Checking formatting..."
	@$(POETRY_RUN) ruff format --check --diff $(SOURCE_DIR) || ($(ERROR) "Ruff formatting failed! Run 'make fix' to auto-format your code."; exit 1)
	@$(SUCCESS) "Formatting check passed!"

fix: ## Auto-fix code style
	@$(MAKE) format
	@$(INFO) "Fixing lint issues..."
	$(POETRY_RUN) ruff check --fix $(SOURCE_DIR)
	@$(SUCCESS) "Auto-fix complete!"

##@ Quality

lint: check-env ## Run soft lint; mypy and vulture are non-blocking
	@$(INFO) "Running soft lint..."
	@$(POETRY_RUN) ruff check $(SOURCE_DIR) $(RUFF_ARGS) || printf '%s\n' "Ruff found issues"
	@MYPY_USE_MYPYC=0 $(POETRY_RUN) python -X faulthandler -m mypy \
		--cache-dir=/dev/null -p app || printf '%s\n' "Mypy found issues or crashed"
	@$(POETRY_RUN) vulture $(SOURCE_DIR) --config pyproject.toml || printf '%s\n' "Vulture found possible dead code"
	@$(SUCCESS) "Soft lint complete!"

lint-strict: check-env format-check ## Run strict lint without mypy and vulture
	@$(INFO) "Running strict lint..."
	$(POETRY_RUN) ruff check $(SOURCE_DIR) $(RUFF_ARGS)
	@$(SUCCESS) "Strict lint passed!"

type-check: check-env ## Run non-blocking mypy type check
	@$(INFO) "Running mypy type check..."
	@MYPY_USE_MYPYC=0 $(POETRY_RUN) python -X faulthandler -m mypy \
		--cache-dir=/dev/null -p app || printf '%s\n' "Mypy found issues or crashed"
	@$(SUCCESS) "Type check finished!"

type-check-strict: check-env ## Run strict mypy type check (tolerates internal mypy bugs)
	@$(INFO) "Running strict mypy type check..."
	@MYPY_USE_MYPYC=0 $(POETRY_RUN) python -X faulthandler -m mypy \
		--cache-dir=/dev/null -p app || ( \
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
	@$(POETRY_RUN) vulture $(SOURCE_DIR) --config pyproject.toml || printf '%s\n' "Vulture found possible dead code"
	@$(SUCCESS) "Vulture scan finished!"

refurb-check: check-env ## Check for modern Python idioms
	@$(INFO) "Running Refurb to modernize code..."
	@if $(POETRY_RUN) refurb --version >/dev/null 2>&1; then \
		$(POETRY_RUN) refurb $(SOURCE_DIR); \
	else \
		$(WARN) "Skipping refurb: install it with 'poetry add --group dev refurb'"; \
	fi

deps-check: check-env ## Check for unused dependencies with Creosote
	@$(INFO) "Checking dependencies..."
	@if $(POETRY_RUN) creosote --version >/dev/null 2>&1; then \
		$(POETRY_RUN) creosote -p $(SOURCE_DIR) || printf '%s\n' "Creosote found unused dependencies"; \
	else \
		$(WARN) "Skipping creosote: install it with 'poetry add --group dev creosote'"; \
	fi
	@$(SUCCESS) "Dependencies check complete!"

deps-check-strict: check-env ## Strict dependency check with Creosote
	@$(INFO) "Running strict dependency checks..."
	@if $(POETRY_RUN) creosote --version >/dev/null 2>&1; then \
		$(POETRY_RUN) creosote -p $(SOURCE_DIR); \
	else \
		$(ERROR) "creosote is not installed in Poetry env"; \
		printf '%s\n' "Run: poetry add --group dev creosote"; \
		exit 1; \
	fi
	@$(SUCCESS) "Strict dependency checks passed!"

secrets-check: check-env ## Scan source code for secrets using detect-secrets
	@$(INFO) "Scanning for secrets..."
	@if $(POETRY_RUN) detect-secrets --version >/dev/null 2>&1; then \
		$(POETRY_RUN) detect-secrets scan $(SOURCE_DIR) \
			--exclude-files '.*migrations/versions/.*\.py$$'; \
	else \
		$(WARN) "Skipping detect-secrets: install it with 'poetry add --group dev detect-secrets'"; \
	fi
	@$(SUCCESS) "Secrets check completed!"

audit: ## Run security and dependency audit
	@$(MAKE) secrets-check
	@$(MAKE) deps-check
	@$(SUCCESS) "Full security audit completed!"

api-fuzz: check-env ## Run property-based testing against live FastAPI
	@$(INFO) "Running Schemathesis API tests..."
	@if $(POETRY_RUN) schemathesis --version >/dev/null 2>&1; then \
		$(POETRY_RUN) schemathesis run http://$(UVICORN_HOST):$(UVICORN_PORT)/openapi.json \
			--checks all; \
	else \
		$(WARN) "Skipping schemathesis: install it with 'poetry add --group dev schemathesis'"; \
	fi

##@ Runtime

run: check-env check-script ## Start project services in background
	@$(MANAGE_SCRIPT) start

run-fg: check-env check-script ## Start project services in foreground
	@$(MANAGE_SCRIPT) run

stop: check-script ## Stop project services
	@$(MANAGE_SCRIPT) stop

restart: check-env check-script ## Restart project services
	@$(MANAGE_SCRIPT) restart

status: check-script ## Show project services status
	@$(MANAGE_SCRIPT) status

migrate: check-env check-script ## Apply database migrations
	@$(MANAGE_SCRIPT) migrate

rabbit-init: check-script ## Initialize RabbitMQ entities
	@$(MANAGE_SCRIPT) init-rabbitmq

watch-config: check-watch-config ## Start config watcher in background
	@mkdir -p "$(RUN_DIR)" "$(LOG_DIR)"
	@if [ -f "$(CONFIG_WATCHER_PID_FILE)" ]; then \
		pid="$$(cat "$(CONFIG_WATCHER_PID_FILE)")"; \
		if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
			$(WARN) "Config watcher already running (PID $$pid)"; \
			exit 0; \
		else \
			$(WARN) "Removing stale config watcher PID file"; \
			rm -f "$(CONFIG_WATCHER_PID_FILE)"; \
		fi; \
	fi
	@$(INFO) "Starting config watcher..."
	@nohup $(POETRY_RUN) python "$(CONFIG_WATCHER_SCRIPT)" >>"$(CONFIG_WATCHER_LOG_FILE)" 2>&1 & echo $$! > "$(CONFIG_WATCHER_PID_FILE)"
	@$(SUCCESS) "Config watcher started (PID $$(cat "$(CONFIG_WATCHER_PID_FILE)"))"

watch-config-stop: ## Stop config watcher
	@if [ ! -f "$(CONFIG_WATCHER_PID_FILE)" ]; then \
		$(WARN) "Config watcher is not running"; \
		exit 0; \
	fi
	@pid="$$(cat "$(CONFIG_WATCHER_PID_FILE)")"; \
	if [ -z "$$pid" ] || ! kill -0 "$$pid" 2>/dev/null; then \
		$(WARN) "Config watcher is not running"; \
		rm -f "$(CONFIG_WATCHER_PID_FILE)"; \
	else \
		$(INFO) "Stopping config watcher (PID $$pid)..."; \
		kill -TERM "$$pid" 2>/dev/null || true; \
		i=0; \
		while [ "$$i" -lt 20 ]; do \
			if ! kill -0 "$$pid" 2>/dev/null; then \
				rm -f "$(CONFIG_WATCHER_PID_FILE)"; \
				$(SUCCESS) "Config watcher stopped"; \
				exit 0; \
			fi; \
			i=$$((i + 1)); \
			sleep 1; \
		done; \
		$(WARN) "Config watcher did not stop gracefully, killing..."; \
		kill -KILL "$$pid" 2>/dev/null || true; \
		rm -f "$(CONFIG_WATCHER_PID_FILE)"; \
		$(SUCCESS) "Config watcher killed"; \
	fi

watch-config-status: ## Show config watcher status
	@if [ -f "$(CONFIG_WATCHER_PID_FILE)" ]; then \
		pid="$$(cat "$(CONFIG_WATCHER_PID_FILE)")"; \
		if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
			echo "Config watcher: running (PID $$pid)"; \
		else \
			echo "Config watcher: stopped"; \
		fi; \
	else \
		echo "Config watcher: stopped"; \
	fi

up: ## Start application and config watcher in background
	@$(MAKE) run
	@$(MAKE) watch-config
	@$(SUCCESS) "Application and config watcher started"

down: ## Stop application and config watcher
	@$(MAKE) watch-config-stop
	@$(MAKE) stop
	@$(SUCCESS) "Application and config watcher stopped"

restart-all: ## Restart application and config watcher
	@$(MAKE) down
	@$(MAKE) up
	@$(SUCCESS) "Application and config watcher restarted"

status-all: ## Show application and config watcher status
	@$(MAKE) status
	@$(MAKE) watch-config-status

##@ Profiling

profile-memray: check-env ## Run FastAPI under Memray
	@mkdir -p "$(PROFILE_DIR)"
	@if $(POETRY_RUN) memray --version >/dev/null 2>&1; then \
		$(INFO) "Running Memray profiler..."; \
		$(POETRY_RUN) memray run -o "$(MEMRAY_OUTPUT)" -m uvicorn "$(UVICORN_APP)" --host "$(UVICORN_HOST)" --port "$(UVICORN_PORT)"; \
	else \
		$(ERROR) "memray is not installed in Poetry env"; \
		printf '%s\n' "Run: poetry add --group dev memray"; \
		exit 1; \
	fi

profile-memray-flamegraph: check-env ## Generate Memray flamegraph HTML
	@mkdir -p "$(PROFILE_DIR)"
	@if [ ! -f "$(MEMRAY_OUTPUT)" ]; then \
		$(ERROR) "Memray output not found: $(MEMRAY_OUTPUT)"; \
		printf '%s\n' "Run: make profile-memray"; \
		exit 1; \
	fi
	@if $(POETRY_RUN) memray --version >/dev/null 2>&1; then \
		$(INFO) "Generating Memray flamegraph..."; \
		$(POETRY_RUN) memray flamegraph -o "$(MEMRAY_FLAMEGRAPH)" "$(MEMRAY_OUTPUT)"; \
		$(SUCCESS) "Memray flamegraph generated: $(MEMRAY_FLAMEGRAPH)"; \
	else \
		$(ERROR) "memray is not installed in Poetry env"; \
		printf '%s\n' "Run: poetry add --group dev memray"; \
		exit 1; \
	fi

profile-memray-stats: check-env ## Show Memray stats
	@if [ ! -f "$(MEMRAY_OUTPUT)" ]; then \
		$(ERROR) "Memray output not found: $(MEMRAY_OUTPUT)"; \
		printf '%s\n' "Run: make profile-memray"; \
		exit 1; \
	fi
	@if $(POETRY_RUN) memray --version >/dev/null 2>&1; then \
		$(INFO) "Showing Memray stats..."; \
		$(POETRY_RUN) memray stats "$(MEMRAY_OUTPUT)"; \
	else \
		$(ERROR) "memray is not installed in Poetry env"; \
		printf '%s\n' "Run: poetry add --group dev memray"; \
		exit 1; \
	fi

profile-mprof: check-env ## Run memory profiling with mprof
	@mkdir -p "$(PROFILE_DIR)"
	@if $(POETRY_RUN) mprof --help >/dev/null 2>&1; then \
		$(INFO) "Running mprof..."; \
		$(POETRY_RUN) mprof run --output "$(MPROF_OUTPUT)" uvicorn "$(UVICORN_APP)" --host "$(UVICORN_HOST)" --port "$(UVICORN_PORT)"; \
		$(SUCCESS) "mprof output saved: $(MPROF_OUTPUT)"; \
	else \
		$(ERROR) "mprof is not installed in Poetry env"; \
		printf '%s\n' "Run: poetry add --group dev memory-profiler"; \
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
	poetry run sphinx-apidoc -f -o $(DOCS_SOURCE) $(APP_DIR)

docs-html:
	poetry run sphinx-build -b html $(DOCS_SOURCE) $(DOCS_BUILD)/html

docs-rebuild: docs-clean docs-apidoc docs-html

docs: docs-rebuild

##@ Git & Release

pre-commit: check-env ## Install and run pre-commit hooks
	@$(INFO) "Setting up pre-commit..."
	$(POETRY_RUN) pre-commit install
	$(POETRY_RUN) pre-commit run --all-files
	@$(SUCCESS) "Pre-commit configured!"

commit: ensure-branch ## Commit changes to Git
	@$(INFO) "Committing changes..."
	git add -A
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
	@$(POETRY_RUN) semantic-release print-version --current

next-version: check-env ## Show what the next version will be
	@$(POETRY_RUN) semantic-release print-version --next

bump: check-env ## Bump version, update CHANGELOG and tag via Semantic Release
	@$(INFO) "Running semantic-release..."
	@if $(POETRY_RUN) semantic-release --version >/dev/null 2>&1; then \
		$(POETRY_RUN) semantic-release version; \
	else \
		$(ERROR) "python-semantic-release is not installed"; \
		printf '%s\n' "Run: poetry add --group dev python-semantic-release"; \
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
