##@ Maintenance
##@ Maintenance

clean: ## Clean temporary files and caches
	@$(INFO) "Cleaning project..."
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".hypothesis" -exec rm -rf {} +
	rm -rf .coverage .coverage.* htmlcov .benchmarks dist build .eggs .run profiles
	@$(SUCCESS) "Cleaning complete!"

clean-all: clean ## Full clean including virtualenv and logs
	@$(INFO) "Removing virtual environment and logs..."
	rm -rf .venv logs
	@$(SUCCESS) "Full clean complete!"

code-clean: ## Alias for clean
	@$(MAKE) clean
	@$(SUCCESS) "Project cleanup finished!"


