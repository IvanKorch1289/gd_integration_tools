##@ Docs
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
	@$(INFO) "Running pytest with --cov + coverage gate (parallel via pytest-xdist, TD-002 fix S53 W4)..."
	$(UV_RUN) pytest tests --cov=src/backend --cov-report=xml --cov-report=term --maxfail=20 -n auto
	$(UV_RUN) python -m coverage combine  # S53 W4: merge per-worker .coverage.<id> files
	$(UV_RUN) python -m coverage report  # S53 W4: regenerate report from combined
	$(UV_RUN) python tools/check_coverage_gate.py --coverage-xml coverage.xml --baseline .baselines/coverage.json --threshold 50
	@$(SUCCESS) "Coverage gate passed"

coverage-gate-strict: ## [wave:s19/k2-w4-coverage-ratchet-75] — coverage gate strict 70→75%
	@$(INFO) "Running pytest with --cov + coverage gate (strict, 75%, parallel via xdist, TD-002 fix S53 W4)..."
	$(UV_RUN) pytest tests --cov=src/backend --cov-report=xml --cov-report=term --maxfail=20 -n auto
	$(UV_RUN) python -m coverage combine  # S53 W4: merge per-worker
	$(UV_RUN) python -m coverage report  # S53 W4: regenerate report
	$(UV_RUN) python tools/check_coverage_gate.py --coverage-xml coverage.xml --baseline .baselines/coverage.json --threshold 75 --strict
	@$(SUCCESS) "Coverage gate strict (75%) passed"

coverage-gate-fast: ## Fast coverage gate (skip pytest, reuse existing coverage.xml)
	@$(INFO) "Running coverage gate (fast, reuse coverage.xml)..."
	$(UV_RUN) python tools/check_coverage_gate.py --coverage-xml coverage.xml --baseline .baselines/coverage.json --threshold 50
	@$(SUCCESS) "Coverage gate (fast) passed"

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


