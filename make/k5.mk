##@ K5 — testkit / chaos / perf / new-plugin
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

lsp-server: check-env ## S42 W1: запуск DSL LSP сервера (stdio) для VS Code / JetBrains / Neovim
	@$(INFO) "Starting DSL LSP server (stdio) — wire up в IDE см. docs/lsp/vscode-config.example.json"
	@$(UV_RUN) python -m src.backend.dsl.cli.lsp_server

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


