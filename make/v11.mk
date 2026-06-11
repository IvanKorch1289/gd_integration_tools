##@ V11 R1.2 — manifest schemas + capability catalog (ADR-042/043/044)
##@ V11 R1.2 — manifest schemas + capability catalog (ADR-042/043/044)

plugin-schema: check-env ## Wave R1.2: dump plugin.toml JSON-Schema → docs/reference/schemas/
	@$(UV_RUN) python tools/export_v11_artefacts.py plugin-schema

route-schema: check-env ## Wave R1.2a: dump route.toml JSON-Schema → docs/reference/schemas/
	@$(UV_RUN) python tools/export_v11_artefacts.py route-schema

capability-catalog: check-env ## Wave R1.1: dump capability vocabulary → docs/reference/capabilities.md
	@$(UV_RUN) python tools/export_v11_artefacts.py capability-catalog

v11-artefacts: check-env ## Wave R1: regenerate plugin/route schemas + capability catalog
	@$(UV_RUN) python tools/export_v11_artefacts.py all

v11-artefacts-check: check-env ## Wave R1: проверить, что committed schemas/capabilities в синке с кодом
	@$(UV_RUN) python tools/check_v11_artefacts.py

check-compat: check-env ## Sprint 14 W1: матрица совместимости plugin.toml::[compatibility]
	@$(UV_RUN) python -m tools.checks.check_compat --plugins-dir extensions/

publish-plugin: check-env ## Sprint 14 W3: bundle + SBOM + cosign + upload плагина (PLUGIN=<name> VERSION=<semver>)
	@if [ -z "$(PLUGIN)" ] || [ -z "$(VERSION)" ]; then \
		echo "Использование: make publish-plugin PLUGIN=<name> VERSION=<semver>"; \
		exit 2; \
	fi
	@$(UV_RUN) python -m tools.publish_plugin --plugin "$(PLUGIN)" --version "$(VERSION)" $(PUBLISH_FLAGS)

plugin-migrate-guide: check-env ## Sprint 14 K5 W1: сгенерировать migration guide PLUGIN=<name> FROM=<ref/path> TO=<ref/path>
	@if [ -z "$(PLUGIN)" ] || [ -z "$(FROM)" ] || [ -z "$(TO)" ]; then \
		echo "Использование: make plugin-migrate-guide PLUGIN=<name> FROM=<git-ref|path> TO=<git-ref|path>"; \
		exit 2; \
	fi
	@$(UV_RUN) python -m tools.plugin_migration_diff --plugin "$(PLUGIN)" --from-ref "$(FROM)" --to-ref "$(TO)"

perf-plugin-sandbox: check-env ## Sprint 14 K2 W2: pytest-benchmark plugin sandbox overhead
	@$(UV_RUN) pytest tests/perf/test_plugin_sandbox_overhead.py --benchmark-only --benchmark-json=tests/perf/baselines/plugin_sandbox.benchmark.json

dsl-stubs: ## Sprint 14 K3 W2: regenerate .pyi stubs for RouteBuilder/WorkflowBuilder
	@.venv/bin/python -m tools.gen_dsl_stubs

dsl-stubs-check: ## Sprint 14 K3 W2: CI gate — нет ли drift между .pyi и runtime
	@.venv/bin/python -m tools.gen_dsl_stubs --check

migrate-plugin-manifest: check-env ## Wave R1.2.b: convert plugins/<name>/plugin.yaml → plugin.toml (PLUGIN_DIR=...)
	@if [ -z "$(PLUGIN_DIR)" ]; then \
		echo "Использование: make migrate-plugin-manifest PLUGIN_DIR=plugins/example_plugin"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/migrate_plugin_manifest.py "$(PLUGIN_DIR)"

migrate-dsl-routes: check-env ## Wave R1.2a.b: wrap dsl_routes/*.yaml into routes/<name>/ (FROM=dsl_routes/ TO=routes/)
	@$(UV_RUN) python tools/migrate_dsl_routes_to_v11.py "$(or $(FROM),dsl_routes)" "$(or $(TO),routes)"

grpc-codegen: check-env ## Wave 1.3: generate .proto + compile pb2/pb2_grpc for gRPC actions
	@APP_PROFILE=dev_light $(UV_RUN) --extra dev-light python tools/codegen_proto.py --clean

grpc-codegen-dry: check-env ## Wave 1.3: dry-run — print plan only
	@APP_PROFILE=dev_light $(UV_RUN) --extra dev-light python tools/codegen_proto.py --dry-run


