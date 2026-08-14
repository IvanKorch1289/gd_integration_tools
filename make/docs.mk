##@ Docs
##@ Docs

# FW3: docs/build pipeline — mkdocs canonical (CLAUDE.md).
# Sphinx tooling удалён (P2-001 RESIDUAL): scripts, docs/api/, AUTOAPI.md.
#
# Использование:
#   make docs-mkdocs              # build mkdocs (canonical, FW3+)
#   make docs-coverage            # docstring + HTML coverage gate

docs-mkdocs: ## FW3: build mkdocs HTML (canonical, per CLAUDE.md)
	@$(INFO) "Building mkdocs (canonical)..."
	$(UV_RUN) mkdocs build --clean --strict
	@$(SUCCESS) "mkdocs build done → $(DOCS_BUILD)/site"

docs-mkdocs-serve: ## FW3: live-reload mkdocs dev server
	@$(INFO) "Starting mkdocs serve on :8000..."
	$(UV_RUN) mkdocs serve --dev-addr 127.0.0.1:8000

docs-clean: ## К10 S2 W5: clean ALL docs build artifacts (mkdocs only)
	rm -rf $(DOCS_BUILD)/*

# DEPRECATED: route → docs-mkdocs.
docs-rebuild: ## DEPRECATED — use docs-mkdocs
	@$(WARN) "docs-rebuild is DEPRECATED → use docs-mkdocs"
	$(MAKE) docs-clean docs-mkdocs

# DEPRECATED: route → docs-mkdocs.
docs: ## DEPRECATED — use docs-mkdocs (mkdocs canonical per CLAUDE.md)
	@$(WARN) "make docs is DEPRECATED → use make docs-mkdocs"
	$(MAKE) docs-mkdocs

docs-coverage: ## Wave 10.8 — docstring + HTML coverage gate
	@$(UV_RUN) python tools/docs_coverage.py --strict

coverage-gate: ## К3 S6 [wave:s6/k3-coverage-gate-70] — pytest coverage gate (blocking, baseline-aware)
	@$(INFO) "Running pytest with --cov + coverage gate (parallel via pytest-xdist, TD-002 fix S53 W4)..."
	$(UV_RUN) pytest tests --cov=src/backend --cov-report=xml --cov-report=term --maxfail=20 -n auto
	$(UV_RUN) python -m coverage combine  # S53 W4: merge per-worker .coverage.<id> files
	$(UV_RUN) python -m coverage report  # S53 W4: regenerate report from combined
	$(UV_RUN) python tools/check_coverage_gate.py --coverage-xml coverage.xml --baseline .baselines/coverage.json --threshold 50 --strict
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
	$(UV_RUN) python tools/check_coverage_gate.py --coverage-xml coverage.xml --baseline .baselines/coverage.json --threshold 50 --strict
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


