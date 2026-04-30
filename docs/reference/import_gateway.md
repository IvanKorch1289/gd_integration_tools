# ImportGateway (W24) — справочник

`ImportGateway` — единый Gateway для импорта внешних спецификаций
(Postman v2.1 / OpenAPI 3.x / WSDL) во внутреннюю модель `ConnectorSpec`.
Заменяет два legacy-стэка (`src/tools/schema_importer/` и
`src/dsl/importers/`).

См. также:

- `src/core/interfaces/import_gateway.py` — Protocol `ImportGateway`,
  enum `ImportSourceKind`, dataclass `ImportSource`.
- `src/core/models/connector_spec.py` — `ConnectorSpec`, `EndpointSpec`,
  `AuthSpec`, `SecretRef`.
- `src/infrastructure/import_gateway/{postman,openapi,wsdl}.py` —
  конкретные backends.
- `src/services/integrations/import_service.py` — orchestration
  (idempotency + persist + register actions).

## Архитектура

```
ImportSource (raw spec + kind + prefix)
        │
        ▼
build_import_gateway(kind)  ← infrastructure/import_gateway/factory.py
        │
        ▼
<Postman|OpenAPI|Wsdl>ImportGateway.import_spec()
        │
        ▼
ConnectorSpec (нормализованный dataclass)
        │
        ▼
ImportService.import_and_register
  ├─ SHA256 idempotency check (через connector_configs)
  ├─ persist в Mongo connector_configs
  ├─ orphan-cleanup (operation_id, исчезнувшие в новом spec)
  ├─ secret_refs_required (без записи значений секретов)
  └─ register_actions (best-effort) → ActionDispatcher
```

## Поддерживаемые форматы

| Kind | Backend | Парсер | Версии |
|---|---|---|---|
| `postman` | `PostmanImportGateway` | самописный (orjson + pydantic) | Postman Collection v2.1 |
| `openapi` | `OpenAPIImportGateway` | `openapi-pydantic` | OpenAPI 3.0.x / 3.1.x |
| `wsdl` | `WsdlImportGateway` | `zeep` | WSDL 1.1, SOAP/HTTP |

## Идемпотентность

`ConnectorSpec.source_hash` — SHA256 от raw content (bytes). Хранится в
`connector_configs.config["source_hash"]`. При повторном импорте того же
spec'а:

- если `source_hash` совпадает с предыдущей записью **и** `force=False`
  → `status=skipped`, `version` не инкрементируется;
- если `force=True` или hash отличается → `status=updated`, version+1.

## Auth → SecretRef

OpenAPI `securitySchemes` и Postman `auth` маппятся в `AuthSpec` с
`SecretRef`-ами. **Сами значения секретов в spec'е не хранятся** —
только ссылки `${VAR_NAME}`. Имена ссылок:

| Источник | Шаблон |
|---|---|
| OpenAPI Bearer | `${OPENAPI_<SCHEME>_TOKEN}` |
| OpenAPI Basic | `${OPENAPI_<SCHEME>_USERNAME}` / `${OPENAPI_<SCHEME>_PASSWORD}` |
| OpenAPI ApiKey | `${OPENAPI_<SCHEME>_VALUE}` |
| OpenAPI OAuth2 | `${OPENAPI_<SCHEME>_ACCESS_TOKEN}` |
| Postman Bearer | `${POSTMAN_BEARER_TOKEN}` |
| Postman Basic | `${POSTMAN_BASIC_USERNAME}` / `${POSTMAN_BASIC_PASSWORD}` |
| Postman ApiKey | `${POSTMAN_API_KEY}` |

Пользователь должен загрузить значения в `SecretsBackend` (Vault или
env+keyring). `secret_refs_required` в ответе импорта содержит список
ключей с подсказками.

## CLI

```bash
# OpenAPI
uv run python manage.py import-schema openapi specs/petstore.yaml --prefix petstore

# Postman
uv run python manage.py import-schema postman collections/slack.json --prefix slack

# WSDL
uv run python manage.py import-schema wsdl wsdl/sap_service.wsdl --prefix sap

# dry-run (без регистрации actions)
uv run python manage.py import-schema openapi specs/petstore.yaml --dry-run
```

## REST

```http
POST /api/v1/imports/openapi
Content-Type: multipart/form-data
file: <openapi-spec>
prefix: petstore
dry_run: false

POST /api/v1/imports/postman
Content-Type: multipart/form-data
file: <postman-collection>
prefix: slack
```

## DSL action

```yaml
- action: connector.import
  payload:
    kind: openapi          # postman | openapi | wsdl
    content: <raw bytes>
    prefix: petstore
    force: false
    dry_run: false

- action: connector.list_imported
  payload: {}
```

## Расширение: новый формат

1. Создать `src/infrastructure/import_gateway/<my_kind>.py` с классом,
   удовлетворяющим Protocol `ImportGateway` (поле `kind`, метод
   `async def import_spec(source) -> ConnectorSpec`).
2. Добавить значение в `ImportSourceKind` enum
   (`core/interfaces/import_gateway.py`).
3. Добавить ветку в `infrastructure/import_gateway/factory.build_import_gateway`.
4. Обновить `tests/unit/import_gateway/test_factory.py` (parametrize
   автоматически подхватит новый kind).
5. Добавить fixture `tests/fixtures/import_gateway/<kind>/*.{ext}`.
6. (Опц.) Документация и пример в этот файл.

## Тесты

- Unit: `tests/unit/import_gateway/test_{postman,openapi,wsdl,factory}.py` (16 тестов).
- Integration: `tests/integration/import_gateway/test_import_service.py`
  (7 тестов, in-memory `_FakeStore` без Mongo).
- Идемпотентность: dual-import + assertion на `version` и `status`.
