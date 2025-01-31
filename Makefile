# Makefile

GIT_COMMIT_MESSAGE ?= "Code quality improvements"
BRANCH ?= main
SOURCE_DIR = ./app
PYTHON = python3.12

.PHONY: format lint clean commit push all help check-env security-check deps-check pre-commit init tag install update lock

## Initialize project with Poetry
init:
	@echo "\033[34mInitializing project...\033[0m"
	poetry config virtualenvs.in-project true
	poetry install --with dev
	@echo "\033[32mProject initialized!\033[0m"

## Install dependencies
install:
	poetry install --with dev

## Update dependencies
update:
	poetry update

## Refresh lock file without updating
lock:
	poetry lock --no-update

## Format code using Black and isort
format:
	@echo "\033[34mFormatting code...\033[0m"
	poetry run black $(SOURCE_DIR)
	poetry run isort $(SOURCE_DIR)
	@echo "\033[32mFormatting complete!\033[0m"

## Lint code using Flake8, mypy, Vulture and Bandit
lint: check-env
	@echo "\033[34mLinting code...\033[0m"
	-poetry run flake8 $(SOURCE_DIR) || echo "Flake8 found issues"
	-poetry run mypy $(SOURCE_DIR) || echo "Mypy found type issues"
	-poetry run vulture $(SOURCE_DIR) --min-confidence 70 --exclude "*/migrations/*,*/tests/*,*/venv/*" || echo "Vulture found dead code"
	-poetry run bandit -r $(SOURCE_DIR) -c .bandit.yml || echo "Bandit found security issues"
	@echo "\033[32mLinting complete (errors ignored)\033[0m"

## Clean temporary files and caches (без удаления .venv)
clean:
	@echo "\033[34mCleaning project...\033[0m"
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	rm -rf .coverage htmlcov .benchmarks
	@echo "\033[32mCleaning complete!\033[0m"

## Full clean including .venv (опционально)
clean-all: clean
	@echo "\033[34mRemoving virtual environment...\033[0m"
	rm -rf .venv
	@echo "\033[32mVirtual environment removed!\033[0m"

## Commit changes to Git
commit: check-env
	@echo "\033[34mCommitting changes...\033[0m"
	git add .
	git commit -m "$(GIT_COMMIT_MESSAGE)" --no-verify

## Push changes to remote repository
push: check-env
	@echo "\033[34mPushing to $(BRANCH)...\033[0m"
	git push origin $(BRANCH)

## Run full workflow: clean -> format -> lint -> commit -> push
all: clean format lint commit push

## Check virtual environment
check-env:
	@if [ -d ".venv" ]; then \
		echo "\033[32mPoetry virtual environment detected\033[0m"; \
	else \
		echo "\033[33mWarning: No virtual environment found. Run 'make init'\033[0m"; \
		exit 1; \
	fi

## Security checks
security-check: check-env
	@echo "\033[34mRunning security checks...\033[0m"
	poetry run safety check
	poetry run pip-audit
	@echo "\033[32mSecurity checks complete!\033[0m"

## Check dependencies health
deps-check: check-env
	@echo "\033[34mChecking dependencies...\033[0m"
	poetry run deptry .
	@echo "\033[32mDependencies check complete!\033[0m"

## Install and run pre-commit hooks
pre-commit:
	@echo "\033[34mSetting up pre-commit...\033[0m"
	poetry run pre-commit install
	poetry run pre-commit run --all-files
	@echo "\033[32mPre-commit configured!\033[0m"

## Create and push version tag
tag:
	@echo "\033[34mCreating version tag...\033[0m"
	git tag $(TAG)
	git push origin $(TAG)
	@echo "\033[32mTag $(TAG) pushed!\033[0m"

## Show this help message
help:
	@echo "\033[34mAvailable commands:\033[0m"
	@echo "  make init         - Initialize project with Poetry"
	@echo "  make install      - Install dependencies"
	@echo "  make update       - Update dependencies"
	@echo "  make lock         - Refresh lock file"
	@echo "  make format       - Format code using Black and isort"
	@echo "  make lint         - Lint code using Flake8, mypy, Vulture and Bandit"
	@echo "  make clean        - Remove temporary files and caches"
	@echo "  make clean-all    - Full clean including .venv (DANGER!)"
	@echo "  make commit       - Commit changes to Git"
	@echo "  make push         - Push changes to remote repository"
	@echo "  make all          - Run full workflow (clean, format, lint, commit, push)"
	@echo "  make security-check - Security audit of dependencies"
	@echo "  make deps-check   - Check dependencies health"
	@echo "  make pre-commit   - Install and run pre-commit hooks"
	@echo "  make tag TAG=vX.X.X - Create and push version tag"
	@echo "  make help         - Show this help"
	@echo ""
	@echo "\033[34mCustom variables:\033[0m"
	@echo "  GIT_COMMIT_MESSAGE - Custom commit message (default: 'Code quality improvements')"
	@echo "  BRANCH             - Target branch (default: main)"
	@echo "  TAG                - Version tag for 'make tag' command"
