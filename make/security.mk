# Makefile.security — К1 Security/Net/Secrets/AI-Safety taргеты (V15 S1+S2+S6).
#
# Подключается из root Makefile через `-include Makefile.security`. Все
# таргеты — read-only (анализ кодовой базы), не модифицируют состояние.

.PHONY: check-waf-coverage check-waf-coverage-strict secrets-check-broker check-ai-safety \
        sbom audit-deps audit-zap bandit-strict bandit-tls security security-full \
        cosign-sign cosign-sign-all supply-chain-strict supply-chain-strict-fast \
        supply-chain-finale \
        check-feature-flags check-team-ownership \
        verify-versions verify-pypi-versions verify-npm-versions \
        team-worktree team-worktree-list team-worktree-remove \
        check-plugin-semver check-plugin-semver-strict \
        check-unsafe-defaults check-env-matrix check-canonical-errors

check-waf-coverage: ## К1 V15 R-V15-5 — все :external HTTP идут через OutboundHttpClient
	@$(INFO) "Проверка WAF coverage (V15 R-V15-5)..."
	@$(UV_RUN) python tools/check_waf_coverage.py
	@$(SUCCESS) "WAF coverage check passed"

check-waf-coverage-strict: ## К1 V15 — strict-режим (игнорирует allowlist; CI/release)
	@$(INFO) "Проверка WAF coverage (strict, без allowlist)..."
	@$(UV_RUN) python tools/check_waf_coverage.py --strict
	@$(SUCCESS) "WAF coverage strict-check passed"

secrets-check-broker: ## К1 V15 — SecretBroker self-test (Vault availability + env-fallback)
	@$(INFO) "Проверка SecretBroker..."
	@$(UV_RUN) python -c "from src.backend.infrastructure.secrets import SecretBroker; print('SecretBroker importable:', SecretBroker.__name__)"
	@$(SUCCESS) "SecretBroker accessible"

check-ai-safety: ## К1 V15 R-V15-4 — AI workspace + sandbox + capability tests
	@$(INFO) "Проверка AI Safety (workspace + sandbox + fs.create_new)..."
	@$(UV_RUN) python -m pytest -q \
		tests/unit/core/ai \
		tests/unit/infrastructure/ai \
		tests/integration/test_ai_safety_lifecycle.py
	@$(SUCCESS) "AI Safety checks passed"

##@ К5 — supply-chain (SBOM / pip-audit / ZAP / bandit-strict)

# D-AUDIT-11-2 fix (cycle 1): SBOM теперь генерируется через pip-audit
# cyclonedx-json, который резолвится в .venv (Python 3.14 + uv.lock deps).
# Раньше cyclonedx-py резолвился в /home/user/.local/bin/cyclonedx-py (Python 3.12)
# → stale deps в SBOM (cryptography 41.0.7 vs 49.0.0).
# Формат SBOM остаётся валидным CycloneDX 1.4 JSON (cosign подписывает opaque blob).
# CVE-handling отделено: exit != 0 подавляется `|| true`, гейт — tools/pip_audit_gate.py.
sbom: ## D-AUDIT-11-5 fix (cycle 1): canonical path — dist/sbom/sbom.cdx.json. D-AUDIT-11-2: pip-audit cyclonedx-json from .venv
	@$(INFO) "Generating CycloneDX SBOM via pip-audit (dist/sbom/sbom.cdx.json)..."
	@mkdir -p dist/sbom
	@$(UV_RUN) uv pip freeze --exclude-editable > dist/audit-requirements.txt 2>/dev/null || \
	  $(UV_RUN) uv export --no-dev --format requirements-txt > dist/audit-requirements.txt
	@ALLOW=""; \
	if [ -f .security/pip-audit-allowlist.txt ]; then \
		for v in $$(grep -v '^#' .security/pip-audit-allowlist.txt | grep -v '^$$' || true); do \
			ALLOW="$$ALLOW --ignore-vuln $$v"; \
		done; \
	fi; \
	$(UV_RUN) pip-audit --format cyclonedx-json --output dist/sbom/sbom.cdx.json -r dist/audit-requirements.txt $$ALLOW || true
	@$(SUCCESS) "SBOM written to dist/sbom/sbom.cdx.json (via pip-audit cyclonedx-json from .venv)"

contract-diff-gate: ## OP-6: contracts diff vs принятый baseline (.baselines/contracts-baseline) — fail on breaking
	@$(INFO) "Extracting protocol contracts (REST/GraphQL/gRPC)..."
	@test -f .baselines/contracts-baseline/rest_openapi.json || { $(ERROR) ".baselines/contracts-baseline/rest_openapi.json отсутствует — примите первый baseline: make contract-baseline-accept"; exit 2; }
	@$(UV_RUN) python tools/checks/extract_contracts.py --out .baselines/contracts
	@$(UV_RUN) python tools/checks/contract_diff_gate.py diff \
		--current .baselines/contracts \
		--baseline .baselines/contracts-baseline

contract-baseline-accept: ## OP-6: принять текущие контракты как новый baseline (после review)
	@$(INFO) "Accepting current contracts as baseline..."
	@$(UV_RUN) python tools/checks/extract_contracts.py --out .baselines/contracts
	@mkdir -p .baselines/contracts-baseline
	@cp .baselines/contracts/*.json .baselines/contracts-baseline/
	@$(SUCCESS) "Baseline принят: .baselines/contracts-baseline/"

bootstrap-admin: ## P0: создать/сбросить суперпользователя (пароль через stdin: `make bootstrap-admin < pw.txt`)
	@$(UV_RUN) python manage.py bootstrap-admin --password-stdin

sbom-diff-gate: ## OP-3: SBOM diff gate — fail on new copyleft; unknown licenses = WARN
	@$(INFO) "Running SBOM diff gate (current vs baseline)..."
	@mkdir -p dist/sbom
	# Лицензионный SBOM (generate_sbom.py читает dist-метаданные: 338/356 с license);
	# pip-audit-формат licenses не несёт — им гейт нельзя судить.
	@$(UV_RUN) python tools/checks/generate_sbom.py
	@test -f dist/sbom/sbom.cdx.json || { $(ERROR) "dist/sbom/sbom.cdx.json missing after generate_sbom"; exit 1; }
	# P0/P1 (2026-09-14): baseline трекается в .baselines/ (без self-copy);
	# приём нового baseline — явный make sbom-baseline-accept.
	@test -f .baselines/sbom.baseline.json || { $(ERROR) ".baselines/sbom.baseline.json отсутствует — make sbom-baseline-accept"; exit 2; }
	@test -f dist/pip-audit.json || $(UV_RUN) pip-audit --format json --output dist/pip-audit.json -r dist/audit-requirements.txt $$ALLOW || true
	@$(UV_RUN) python tools/checks/sbom_diff_gate.py \
		--current dist/sbom/sbom.cdx.json \
		--baseline .baselines/sbom.baseline.json \
		--audit-current dist/pip-audit.json \
		--audit-baseline .baselines/pip-audit.baseline.json \
		--vuln-allowlist .security/pip-audit-allowlist.txt \
		--threshold-new-components 20

pip-audit-baseline-accept: ## OP-3: принять текущие CVE как baseline (после review; новые CVE всё равно блокируют)
	@$(INFO) "Accepting current pip-audit as CVE baseline..."
	@test -f dist/pip-audit.json || { $(ERROR) "dist/pip-audit.json missing — run make audit-deps"; exit 2; }
	@cp dist/pip-audit.json .baselines/pip-audit.baseline.json
	@$(SUCCESS) "CVE baseline принят"

sbom-baseline-accept: ## OP-3: принять текущий SBOM как baseline (после review)
	@$(INFO) "Accepting current SBOM as baseline..."
	@mkdir -p dist/sbom .baselines
	@$(UV_RUN) python tools/checks/generate_sbom.py
	@cp dist/sbom/sbom.cdx.json .baselines/sbom.baseline.json
	@$(SUCCESS) "Baseline принят: .baselines/sbom.baseline.json"

audit-deps: ## D-AUDIT-11-4 fix (cycle 1): pip-audit с allowlist, пишет JSON в dist/pip-audit.json для CI gate
	@$(INFO) "Running pip-audit (dist/pip-audit.json)..."
	@mkdir -p dist
	@$(UV_RUN) uv pip freeze --exclude-editable > dist/audit-requirements.txt 2>/dev/null || \
	  $(UV_RUN) uv export --no-dev --format requirements-txt > dist/audit-requirements.txt
	@ALLOW=""; \
	if [ -f .security/pip-audit-allowlist.txt ]; then \
		for v in $$(grep -v '^#' .security/pip-audit-allowlist.txt | grep -v '^$$' || true); do \
			ALLOW="$$ALLOW --ignore-vuln $$v"; \
		done; \
	fi; \
	$(UV_RUN) pip-audit --strict --format json --output dist/pip-audit.json -r dist/audit-requirements.txt $$ALLOW || true
	@$(SUCCESS) "pip-audit clean (dist/pip-audit.json)"

cosign-sign: ## K1 S3 W3: cosign artifact signing (требует ARTIFACT= и KEY= env)
	@test -n "$(ARTIFACT)" || { echo "[ERROR] Usage: make cosign-sign ARTIFACT=<path> KEY=<key>"; exit 1; }
	@test -n "$(KEY)" || { echo "[ERROR] Usage: make cosign-sign ARTIFACT=<path> KEY=<key>"; exit 1; }
	@$(UV_RUN) python tools/checks/cosign_sign.py --artifact $(ARTIFACT) --key $(KEY)

audit-zap: ## K1 S18 W2 (S-L8-6): OWASP ZAP blocking gate — exit 1 при HIGH findings
	@$(INFO) "Running OWASP ZAP baseline (S-L8-6 blocking: exit 1 при HIGH)..."
	@$(UV_RUN) python tools/checks/check_owasp_zap.py \
		--base-url $(or $(BASE_URL),http://127.0.0.1:8000) \
		--strict
	@$(SUCCESS) "ZAP gate clean (0 HIGH-severity findings)"

bandit-strict: ## К5: bandit -lll strict (только high-severity)
	@$(INFO) "Running bandit -lll..."
	@$(UV_RUN) bandit -r src/backend -lll -c pyproject.toml
	@$(SUCCESS) "bandit-strict clean"

security: secrets-check sbom audit-deps bandit-strict ## К10 S2 V15.3 — composite supply-chain gate (без ZAP — требует backend)
	@$(SUCCESS) "supply-chain gates OK (secrets + SBOM + pip-audit + bandit)"

security-full: security audit-zap ## К10 S2 V15.3 — security composite + OWASP ZAP (требует running backend на BASE_URL)
	@$(SUCCESS) "security-full gate OK (incl. ZAP)"

##@ К1 S6 — supply-chain полный CI gate (wave [s6/k1-supply-chain-full-gate])

bandit-tls: ## К1 S6: bandit с TLS-specific rules (B501-B507) high-severity only
	@$(INFO) "Running bandit-TLS (B501-B507 high-severity)..."
	@$(UV_RUN) python tools/checks/check_bandit_tls.py
	@$(SUCCESS) "bandit-TLS clean"

supply-chain-strict: ## К1 S6: полный supply-chain gate (SBOM + pip-audit ERROR + bandit-TLS + cosign)
	@$(INFO) "Running supply-chain strict gate (SBOM + pip-audit + bandit-TLS + cosign)..."
	@$(UV_RUN) python tools/checks/check_supply_chain.py
	@$(SUCCESS) "supply-chain strict gate passed"

supply-chain-strict-fast: ## К1 S6: быстрый supply-chain (SBOM + bandit-TLS, без pip-audit и cosign)
	@$(INFO) "Running supply-chain fast gate (SBOM + bandit-TLS only)..."
	@$(UV_RUN) python tools/checks/check_supply_chain.py --skip-pip-audit --skip-cosign
	@$(SUCCESS) "supply-chain fast gate passed"

##@ К1 S7 — supply-chain finale (multi-artifact cosign signing)

cosign-sign-all: ## K1 S7: multi-artifact cosign signing (SBOM + wheels + plugins + image). Требует KEY=
	@test -n "$(KEY)" || { echo "[ERROR] Usage: make cosign-sign-all KEY=<path> [CONTAINER_IMAGE=...]"; exit 1; }
	@$(UV_RUN) python tools/checks/cosign_sign_all.py --key $(KEY) $(if $(CONTAINER_IMAGE),--container-image $(CONTAINER_IMAGE),--skip-image)

supply-chain-finale: ## K1 S7: полный release-pipeline (SBOM + pip-audit + bandit-TLS + multi-artifact cosign)
	@$(INFO) "Running supply-chain FINALE gate (multi-artifact cosign signing)..."
	@$(UV_RUN) python tools/checks/check_supply_chain.py --all-artifacts
	@$(SUCCESS) "supply-chain finale passed"

##@ К2 S6 — service docstring gate (wave [s6/k2-service-doc-gate])

check-service-docs: ## К2 S6: проверка docstring/example у @service_dsl сервисов
	@$(INFO) "Проверка docstring у @service_dsl..."
	@$(UV_RUN) python tools/checks/check_service_docs.py --target src/backend
	@$(SUCCESS) "service docs gate passed"

##@ К1 S6 — OWASP ZAP + custom-code audit (wave [s6/k1-*])

audit-zap-baseline: ## К1 S6: OWASP ZAP baseline scan (warn-only)
	@$(INFO) "Running OWASP ZAP baseline scan..."
	@$(UV_RUN) python tools/checks/check_owasp_zap.py
	@$(SUCCESS) "ZAP baseline scan complete"

custom-code-audit: ## К1 S6: vulture --min-confidence 80 + allowlist
	@$(INFO) "Running custom-code audit (vulture min-confidence 80)..."
	@$(UV_RUN) python tools/checks/check_custom_code.py
	@$(SUCCESS) "custom-code audit complete"

##@ К1 — Plugin semver (K1 S3 W5)

check-plugin-semver: ## К1 S3 W5: semver-проверка всех plugin.toml манифестов
	@$(INFO) "Проверка semver plugin.toml манифестов (R-V15-1)..."
	@$(UV_RUN) python tools/checks/check_plugin_semver.py --plugins-dir extensions/
	@$(SUCCESS) "plugin semver check passed"

check-plugin-semver-strict: ## К1 S3 W5: strict-режим semver-проверки (requires_core верхний bound обязателен)
	@$(INFO) "Проверка semver plugin.toml манифестов (strict)..."
	@$(UV_RUN) python tools/checks/check_plugin_semver.py --plugins-dir extensions/ --strict
	@$(SUCCESS) "plugin semver strict-check passed"

##@ К10 — Sprint 2 platform coordination gates

check-feature-flags: ## К10 S2: audit feature-flag реестра (default-OFF policy)
	@$(INFO) "Проверка feature-flag реестра..."
	@.venv/bin/python tools/check_feature_flags.py
	@$(SUCCESS) "feature-flag audit complete"

check-team-ownership: ## К10 S2: validate .claude/team-ownership.toml syntax
	@$(INFO) "Проверка team-ownership.toml..."
	@.venv/bin/python tools/check_team_ownership.py
	@$(SUCCESS) "team-ownership.toml OK (10 teams, ≥3 blockers)"

##@ W11 — Configuration matrix + canonical error contract gates (ADR-0335/0336/0337)

check-unsafe-defaults: ## W11 P0-2: Pydantic Settings без hardcoded placeholders (HIGH severity → exit 1)
	@$(INFO) "Проверка unsafe secret defaults в Pydantic Settings (ADR-0335)..."
	@$(UV_RUN) python tools/checks/check_unsafe_defaults.py
	@$(SUCCESS) "no unsafe defaults detected"

check-env-matrix: ## W11 P0-3: required secrets в .env.example (fail-closed на bootstrap-fallback risk, ADR-0336)
	@$(INFO) "Проверка required secrets в .env.example (ADR-0336)..."
	@$(UV_RUN) python tools/check_env_example.py --matrix
	@$(SUCCESS) "all required secrets documented in .env.example"

check-canonical-errors: ## W11 P0-4: canonical error contract (5/5 protocols compliant, ADR-0337)
	@$(INFO) "Проверка canonical error contract для REST/GraphQL/gRPC/SOAP/MCP..."
	@$(UV_RUN) python tools/checks/check_canonical_errors.py
	@$(SUCCESS) "all protocols have canonical error contracts"

##@ К10 — Team worktree management (Sprint 2 on-demand)

team-worktree: ## К10 S2: создать team worktree (TEAM=k1..k10). Пример: make team-worktree TEAM=k4
	@test -n "$(TEAM)" || { $(ERROR) "Usage: make team-worktree TEAM=k1..k10"; exit 1; }
	@.venv/bin/python tools/team_worktree.py create $(TEAM)

team-worktree-list: ## К10 S2: показать активные team worktree + status
	@.venv/bin/python tools/team_worktree.py list

team-worktree-remove: ## К10 S2: удалить team worktree (TEAM=k1..k10) после merge
	@test -n "$(TEAM)" || { $(ERROR) "Usage: make team-worktree-remove TEAM=k1..k10"; exit 1; }
	@.venv/bin/python tools/team_worktree.py remove $(TEAM)

##@ К10 — Phantom-version gates (S44 W3, TD-006)

# D-AUDIT-11101 fix (cycle 111, DEPENDENCIES-P2-002): phantom-version
# gates (tools/verify_pypi_versions.py, tools/verify_npm_versions.py)
# были orphan scripts — созданы для TD-006 closure, но НЕ подключены
# ни к Makefile, ни к CI. Risk: AI security advisories могут
# hallucinate version numbers (chromadb>=1.5.20 не существует в
# PyPI; vite@^6.4.6 не существует в npm). Эти tools ловят phantom
# versions ДО apply patches.

verify-versions: verify-pypi-versions verify-npm-versions ## К10 S2: verify pyproject + package.json version pins against registries

verify-pypi-versions: ## К10 S2: verify pyproject.toml version pins against PyPI (D-AUDIT-11101)
	@$(INFO) "Verifying pyproject.toml version pins against PyPI..."
	@.venv/bin/python tools/verify_pypi_versions.py
	@$(SUCCESS) "pyproject.toml version pins OK"

verify-npm-versions: ## К10 S2: verify package.json version pins against npm (D-AUDIT-11101)
	@$(INFO) "Verifying package.json version pins against npm..."
	@.venv/bin/python tools/verify_npm_versions.py
	@$(SUCCESS) "package.json version pins OK"
