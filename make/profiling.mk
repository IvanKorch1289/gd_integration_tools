##@ Profiling
##@ Profiling

profile-memray: check-env ## Run FastAPI under Memray
	@mkdir -p "$(PROFILE_DIR)"
	@if $(UV_RUN) memray --version >/dev/null 2>&1; then \
		$(INFO) "Running Memray profiler..."; \
		$(UV_RUN) memray run -o "$(MEMRAY_OUTPUT)" -m uvicorn "$(UVICORN_APP)" --host "$(UVICORN_HOST)" --port "$(UVICORN_PORT)"; \
	else \
		$(ERROR) "memray is not installed in uv env"; \
		printf '%s\n' "Run: uv add --dev memray"; \
		exit 1; \
	fi

profile-memray-flamegraph: check-env ## Generate Memray flamegraph HTML
	@mkdir -p "$(PROFILE_DIR)"
	@if [ ! -f "$(MEMRAY_OUTPUT)" ]; then \
		$(ERROR) "Memray output not found: $(MEMRAY_OUTPUT)"; \
		printf '%s\n' "Run: make profile-memray"; \
		exit 1; \
	fi
	@if $(UV_RUN) memray --version >/dev/null 2>&1; then \
		$(INFO) "Generating Memray flamegraph..."; \
		$(UV_RUN) memray flamegraph -o "$(MEMRAY_FLAMEGRAPH)" "$(MEMRAY_OUTPUT)"; \
		$(SUCCESS) "Memray flamegraph generated: $(MEMRAY_FLAMEGRAPH)"; \
	else \
		$(ERROR) "memray is not installed in uv env"; \
		printf '%s\n' "Run: uv add --dev memray"; \
		exit 1; \
	fi

profile-memray-stats: check-env ## Show Memray stats
	@if [ ! -f "$(MEMRAY_OUTPUT)" ]; then \
		$(ERROR) "Memray output not found: $(MEMRAY_OUTPUT)"; \
		printf '%s\n' "Run: make profile-memray"; \
		exit 1; \
	fi
	@if $(UV_RUN) memray --version >/dev/null 2>&1; then \
		$(INFO) "Showing Memray stats..."; \
		$(UV_RUN) memray stats "$(MEMRAY_OUTPUT)"; \
	else \
		$(ERROR) "memray is not installed in uv env"; \
		printf '%s\n' "Run: uv add --dev memray"; \
		exit 1; \
	fi

profile-mprof: check-env ## Run memory profiling with mprof
	@mkdir -p "$(PROFILE_DIR)"
	@if $(UV_RUN) mprof --help >/dev/null 2>&1; then \
		$(INFO) "Running mprof..."; \
		$(UV_RUN) mprof run --output "$(MPROF_OUTPUT)" uvicorn "$(UVICORN_APP)" --host "$(UVICORN_HOST)" --port "$(UVICORN_PORT)"; \
		$(SUCCESS) "mprof output saved: $(MPROF_OUTPUT)"; \
	else \
		$(ERROR) "mprof is not installed in uv env"; \
		printf '%s\n' "Run: uv add --dev memory-profiler"; \
		exit 1; \
	fi

profile-pyspy: ## Record CPU profile with py-spy
	@mkdir -p "$(PROFILE_DIR)"
	@if command -v py-spy >/dev/null 2>&1; then \
		$(INFO) "Recording py-spy profile..."; \
		py-spy record -o "$(PYSPY_OUTPUT)" -- python -m uvicorn "$(UVICORN_APP)" --host "$(UVICORN_HOST)" --port "$(UVICORN_PORT)"; \
		$(SUCCESS) "py-spy profile saved: $(PYSPY_OUTPUT)"; \
	else \
		$(ERROR) "py-spy is not installed on host"; \
		printf '%s\n' "Install: pip install py-spy"; \
		exit 1; \
	fi


