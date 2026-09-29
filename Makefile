
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

# Верхняя граница времени одного unit-теста (секунды). pytest-timeout
# обязателен: без него зависший тест подвешивает пайплайн без границы
# (12 @pytest.mark.timeout(N) были no-op до audit 2026-09-29).
# Существующие маркеры в сьюте: 5s / 15s / 30s / 120s / 180s.
UNIT_TEST_TIMEOUT ?= 120

# Число xdist-воркеров для unit-тестов.
#
# ВАЖНО: не ставьте ``-n auto``, не проверив запас RAM. Измерено
# 2026-09-29 на машине 15 ГБ / 4 ядра: ``-n auto`` (4 воркера) доводит прогон
# до 99%, после чего воркеры убиваются OOM-killer'ом (14/15 ГБ занято,
# 247 событий OOM в kern.log), становятся зомби, а xdist-контроллер
# БЕСКОНЕЧНО ждёт мёртвый воркер. Прогон не падает — он висит.
#
# ``pytest-timeout`` от этого не спасает: он ограничивает ЗАВИСШИЙ ТЕСТ,
# а здесь процесс убивается снаружи. Проверено фактически, не по догадке.
#
# Значение 2 подтверждено сегментированным прогоном 36/61 сегментов без
# единого OOM. На раннере с большим запасом RAM поднимайте явно:
#   make unit-tests UNIT_TEST_JOBS=4
UNIT_TEST_JOBS ?= 2
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
	vulture-check refurb-check check-docstrings \
	clean clean-all code-clean \
	run run-fg stop restart status migrate rabbit-init frontend streamlit \
	profile-memray profile-memray-flamegraph profile-memray-stats profile-mprof profile-pyspy \
	deps-check deps-check-strict \
	secrets-check audit api-fuzz \
	mutation mutation-quick mutation-gate \
	pre-commit commit push git-sync \
	current-version next-version bump \
	code-lint code-check check-strict check-strict-full \
	fix-check-push ship ship-release \
	docker-build docker-run docker-stop \
	tag all \
	docs-clean docs-rebuild docs \
	layers layers-update config-audit check-mro \
	config-new config-apply config-extract \
	new-service new-repository codegen-extract \
	import-swagger import-postman import-wsdl \
	testkit-smoke new-plugin new-middleware \
	perf-smoke perf-full perf-gate perf-gate-py perf-baseline chaos chaos-slow docs-vale \
	arch-ratchet \
new-adr release-notes

.PHONY: new-middleware
new-middleware: ##@ Scaffolding Scaffold new ASGI middleware (D136)
	@uv run python ops/scripts/new_middleware.py $(NAME) $(ARGS)

help: ##@ Misc Show this help
	@printf "\nUsage:\n  make \033[36m<target>\033[0m\n"
	@awk 'BEGIN {FS = ":.*## "}; \
		/^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next} \
		/^[a-zA-Z0-9_.-]+:.*## / {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\n"


# === Org-4 (S64): split per-section into make/*.mk ===
# Total: 179 targets → 16 .mk files. Root Makefile = thin wrapper.
# Run \ to see all targets.
-include make/setup.mk
-include make/formatting.mk
-include make/quality.mk
-include make/runtime.mk
-include make/v11.mk
-include make/codegen.mk
-include make/k5.mk
-include make/profiling.mk
-include make/docs.mk
-include make/git.mk
-include make/pipelines.mk
-include make/maintenance.mk
-include make/docker.mk
-include make/prod.mk
-include make/quickwins.mk
-include make/agent.mk

