##@ Pipelines
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
	@$(MAKE) check-waf-coverage-strict
	@$(SUCCESS) "All strict checks passed!"

ci: ## К1 V15 — composite CI gate (lint + type + tests + security + WAF strict)
	@$(MAKE) format-check
	@$(MAKE) lint-strict
	@$(MAKE) type-check-strict
	@$(MAKE) deps-check-strict
	@$(MAKE) secrets-check
	@$(MAKE) check-waf-coverage-strict
	@$(MAKE) check-ai-safety
	@$(MAKE) check-python3-syntax
	@$(MAKE) check-task-registry
	@$(SUCCESS) "CI gate passed"

pr: ## К1 V15 — composite PR gate (ci + docs)
	@$(MAKE) ci
	@$(MAKE) docs
	@$(SUCCESS) "PR gate passed"

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


