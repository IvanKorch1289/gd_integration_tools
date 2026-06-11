##@ Codegen Wave 5
##@ Codegen Wave 5

new-service: check-env ## Scaffold service+repo+schema+action (NAME=plural DOMAIN=core [CRUD=1] [FIELDS='{"k":"str"}'])
	@if [ -z "$(NAME)" ] || [ -z "$(DOMAIN)" ]; then \
		echo "Использование: make new-service NAME=<plural> DOMAIN=<area> [CRUD=1] [FIELDS='{...}']"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/codegen_service.py --name "$(NAME)" --domain "$(DOMAIN)" \
		$(if $(CRUD),--crud,) $(if $(FIELDS),--fields '$(FIELDS)',) \
		$(if $(MODEL_CLASS),--model-class "$(MODEL_CLASS)",) \
		$(if $(OVERWRITE),--overwrite,)

new-repository: check-env ## Scaffold sqlalchemy repository (NAME=plural [MODEL_CLASS=Name])
	@if [ -z "$(NAME)" ]; then \
		echo "Использование: make new-repository NAME=<plural> [MODEL_CLASS=Name]"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/codegen_repository.py --name "$(NAME)" \
		$(if $(MODEL_CLASS),--model-class "$(MODEL_CLASS)",) \
		$(if $(OVERWRITE),--overwrite,)

codegen-extract: check-env ## Reverse codegen: service.py → YAML (SERVICE=<path> [OUTPUT=-])
	@if [ -z "$(SERVICE)" ]; then \
		echo "Использование: make codegen-extract SERVICE=<path> [OUTPUT=-]"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/codegen_extract.py --service "$(SERVICE)" --output "$(or $(OUTPUT),-)"

import-swagger: check-env ## Swagger/OpenAPI → actions (URL=<spec> CONNECTOR=<name> [WRITE=1])
	@if [ -z "$(URL)" ] || [ -z "$(CONNECTOR)" ]; then \
		echo "Использование: make import-swagger URL=<spec> CONNECTOR=<name> [WRITE=1]"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/import_swagger.py --url "$(URL)" --connector "$(CONNECTOR)" \
		$(if $(WRITE),--write,) $(if $(OUTPUT_DIR),--output-dir "$(OUTPUT_DIR)",)

import-postman: check-env ## Postman v2.1 → actions (FILE=<json> CONNECTOR=<name> [WRITE=1])
	@if [ -z "$(FILE)" ] || [ -z "$(CONNECTOR)" ]; then \
		echo "Использование: make import-postman FILE=<json> CONNECTOR=<name> [WRITE=1]"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/import_postman.py --file "$(FILE)" --connector "$(CONNECTOR)" \
		$(if $(WRITE),--write,) $(if $(OUTPUT_DIR),--output-dir "$(OUTPUT_DIR)",)

import-wsdl: check-env ## WSDL → actions (URL=<wsdl> CONNECTOR=<name> [WRITE=1])
	@if [ -z "$(URL)" ] || [ -z "$(CONNECTOR)" ]; then \
		echo "Использование: make import-wsdl URL=<wsdl> CONNECTOR=<name> [WRITE=1]"; \
		exit 2; \
	fi
	@$(UV_RUN) python tools/import_wsdl.py --url "$(URL)" --connector "$(CONNECTOR)" \
		$(if $(WRITE),--write,) $(if $(OUTPUT_DIR),--output-dir "$(OUTPUT_DIR)",)


