##@ Docker
##@ Docker

docker-build: check-docker ## Build Docker image
	@$(INFO) "Building Docker image $(IMAGE_NAME):$(IMAGE_TAG)..."
	$(DOCKER) build -t $(IMAGE_NAME):$(IMAGE_TAG) .
	@$(SUCCESS) "Docker image built!"

docker-run: check-docker ## Run Docker container
	@$(INFO) "Running Docker container..."
	$(DOCKER) run --rm \
		-p 8000:8000 \
		-p 4200:4200 \
		-p 50051:50051 \
		--name $(IMAGE_NAME) \
		$(IMAGE_NAME):$(IMAGE_TAG)

docker-stop: check-docker ## Stop Docker container
	@$(INFO) "Stopping Docker container..."
	-$(DOCKER) stop $(IMAGE_NAME)
	@$(SUCCESS) "Docker container stopped!"

# ── Compose stacks (Sprint 54 W2) ─────────────────────────────────────
# Light:  app + worker only (SQLite/in-memory, no postgres/redis/clamav).
# Full:   app + worker + postgres + redis + clamav + migration-runner.
COMPOSE_FILE_FULL  := ops/compose/docker-compose.yml
COMPOSE_FILE_LIGHT := ops/compose/docker-compose.light.yml
COMPOSE_FILE_PLUGIN_DEV := ops/compose/docker-compose.plugin-dev.yml

up-full: check-docker ## Start full stack (postgres + redis + clamav + app + worker)
	@$(INFO) "Starting full stack from $(COMPOSE_FILE_FULL)..."
	$(DOCKER) compose -f $(COMPOSE_FILE_FULL) up -d --build
	@$(SUCCESS) "Full stack up. Run 'make logs-full' to follow logs."

up-light: check-docker ## Start light stack (app + worker, no infra, APP_PROFILE=dev_light)
	@$(INFO) "Starting light stack from $(COMPOSE_FILE_LIGHT)..."
	$(DOCKER) compose -f $(COMPOSE_FILE_LIGHT) up -d --build
	@$(SUCCESS) "Light stack up. App: http://localhost:8000"

up-plugin-dev: check-docker ## Start plugin-dev stack (postgres + redis, no app)
	@$(INFO) "Starting plugin-dev infra from $(COMPOSE_FILE_PLUGIN_DEV)..."
	$(DOCKER) compose -f $(COMPOSE_FILE_PLUGIN_DEV) up -d
	@$(SUCCESS) "Plugin-dev infra up (postgres:5433, redis:6380)."

down-full: check-docker ## Stop full stack (keeps volumes)
	$(DOCKER) compose -f $(COMPOSE_FILE_FULL) down
	@$(SUCCESS) "Full stack down."

down-light: check-docker ## Stop light stack
	$(DOCKER) compose -f $(COMPOSE_FILE_LIGHT) down
	@$(SUCCESS) "Light stack down."

down-plugin-dev: check-docker ## Stop plugin-dev stack
	$(DOCKER) compose -f $(COMPOSE_FILE_PLUGIN_DEV) down
	@$(SUCCESS) "Plugin-dev stack down."

logs-full: check-docker ## Tail full stack logs
	$(DOCKER) compose -f $(COMPOSE_FILE_FULL) logs -f

logs-light: check-docker ## Tail light stack logs
	$(DOCKER) compose -f $(COMPOSE_FILE_LIGHT) logs -f

ps-full: check-docker ## Show full stack status
	$(DOCKER) compose -f $(COMPOSE_FILE_FULL) ps

ps-light: check-docker ## Show light stack status
	$(DOCKER) compose -f $(COMPOSE_FILE_LIGHT) ps

restart-light: down-light up-light ## Restart light stack
restart-full: down-full up-full ## Restart full stack

clean-volumes: check-docker ## Remove all named volumes (postgres data, redis data, clamav db)
	@$(WARN) "This will DELETE all local data volumes (postgres, redis, clamav)."
	@read -p "Continue? [y/N] " r && [ "$$r" = "y" ] || exit 1
	$(DOCKER) compose -f $(COMPOSE_FILE_FULL) down -v
	@$(SUCCESS) "Volumes removed."

tag: ## Create and push version tag (legacy)
	@if [ -z "$(TAG)" ]; then \
		$(ERROR) "TAG is required. Example: make tag TAG=v1.2.3"; \
		exit 1; \
	fi
	@$(INFO) "Creating version tag..."
	git tag $(TAG)
	git push origin $(TAG)
	@$(SUCCESS) "Tag $(TAG) pushed!"


