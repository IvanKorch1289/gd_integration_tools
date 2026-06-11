##@ Setup
##@ Setup

init: ## Initialize project with uv
	@$(INFO) "Initializing project..."
	uv sync --all-extras
	@$(SUCCESS) "Project initialized!"

onboarding: check-env ## S42 W2: интерактивный onboarding wizard (5 шагов: preflight → uv sync → doctor → precommit → sample)
	@$(INFO) "Запуск onboarding wizard (Typer + questionary + rich)..."
	@$(UV_RUN) python tools/wizards/onboarding_wizard.py

onboarding-non-interactive: check-env ## S42 W2: non-interactive onboarding (для CI / scripted setup)
	@$(UV_RUN) python tools/wizards/onboarding_wizard.py --non-interactive

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


