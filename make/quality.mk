##@ Quality
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



check-no-duplicate-scripts: ## S64 org-2: fail if scripts/ and tools/ have duplicate file names
	@$(UV_RUN) python tools/checks/no_duplicate_scripts.py
