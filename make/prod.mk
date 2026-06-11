##@ Production Readiness
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


