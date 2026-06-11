##@ Git & Release
##@ Git & Release

pre-commit: check-env ## Install and run pre-commit hooks
	@$(INFO) "Setting up pre-commit..."
	$(UV_RUN) pre-commit install
	$(UV_RUN) pre-commit run --all-files
	@$(SUCCESS) "Pre-commit configured!"

commit: ensure-branch ## Commit changes to Git (explicit paths — no -A)
	@$(INFO) "Committing changes (explicit paths, no -A)..."
	@# A2 security: запрещаем git add -A, чтобы исключить добавление
	@# случайных файлов (.env, artifacts, IDE-cruft, секреты).
	git add src/ docs/ tools/ tools/ pyproject.toml uv.lock Makefile .pre-commit-config.yaml .gitignore 2>/dev/null || true
	@# Опциональные корневые файлы — добавляются, только если существуют.
	@[ -f .gitlab-ci.yml ] && git add .gitlab-ci.yml || true
	@[ -f ops/compose/Dockerfile ] && git add ops/compose/Dockerfile || true
	@[ -f ops/compose/docker-compose.yml ] && git add ops/compose/docker-compose.yml || true
	@if git diff --cached --quiet; then \
		$(WARN) "Nothing to commit"; \
	else \
		if [ "$(GIT_NO_VERIFY)" = "1" ]; then \
			git commit -m "$(GIT_COMMIT_MESSAGE)" --no-verify; \
		else \
			git commit -m "$(GIT_COMMIT_MESSAGE)"; \
		fi; \
	fi

current-version: check-env ## Show current semantic version
	@$(UV_RUN) semantic-release print-version --current

next-version: check-env ## Show what the next version will be
	@$(UV_RUN) semantic-release print-version --next

bump: check-env ## Bump version, update CHANGELOG and tag via Semantic Release
	@$(INFO) "Running semantic-release..."
	@if $(UV_RUN) semantic-release --version >/dev/null 2>&1; then \
		$(UV_RUN) semantic-release version; \
	else \
		$(ERROR) "python-semantic-release is not installed"; \
		printf '%s\n' "Run: uv add --dev python-semantic-release"; \
		exit 1; \
	fi

push: ensure-branch ## Push changes and tags to remote repository
	@$(INFO) "Pushing to $(BRANCH)..."
	git push -u origin $(BRANCH)
	git push --tags

git-sync: ## Commit and push current branch
	@$(MAKE) commit
	@$(MAKE) push
	@$(SUCCESS) "Git sync finished!"


