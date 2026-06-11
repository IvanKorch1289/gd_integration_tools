##@ Formatting
##@ Formatting

format: check-env ## Format code using Ruff
	@$(INFO) "Formatting code..."
	$(UV_RUN) ruff check --select I --fix $(SOURCE_DIR)
	$(UV_RUN) ruff format $(SOURCE_DIR)
	@$(SUCCESS) "Formatting complete!"

format-check: check-env ## Check formatting without modifying files
	@$(INFO) "Checking formatting..."
	@$(UV_RUN) ruff format --check --diff $(SOURCE_DIR) || ($(ERROR) "Ruff formatting failed! Run 'make fix' to auto-format your code."; exit 1)
	@$(SUCCESS) "Formatting check passed!"

fix: ## Auto-fix code style
	@$(MAKE) format
	@$(INFO) "Fixing lint issues..."
	$(UV_RUN) ruff check --fix $(SOURCE_DIR)
	@$(SUCCESS) "Auto-fix complete!"


