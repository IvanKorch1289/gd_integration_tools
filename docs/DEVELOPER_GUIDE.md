# Developer Guide

## Adding a New Service

1. Create repository in `src/infrastructure/repositories/`:
```python
@singleton
class MyRepository(BaseRepository[MyModel]):
    pass

def get_my_repo() -> MyRepository:
    return MyRepository(model=MyModel)
```

2. Create service in `src/services/`:
```python
@singleton
class MyService(BaseService[MyRepository, MySchemaOut, MySchemaIn, MyVersionSchema]):
    def __init__(self, repo, schema_in, schema_out, version_schema):
        super().__init__(repo=repo, request_schema=schema_in, ...)

def get_my_service() -> MyService:
    return MyService(repo=get_my_repo(), ...)
```

3. Register in `src/core/service_setup.py`.

## Adding a New Action

1. Define spec in endpoint file:
```python
action = ActionSpec(
    name="my.action",
    method="POST",
    path="/my-action/",
    summary="Do something",
    service_getter=get_my_service,
    service_method="do_something",
    body_model=MyInputSchema,
    response_model=MyOutputSchema,
)
```

2. Register: `builder.add_action(action)`

## Adding a CRUD Resource

```python
crud = CrudSpec(
    name="widgets",
    service_getter=get_widget_service,
    schema_in=WidgetSchemaIn,
    schema_out=WidgetSchemaOut,
)
builder.add_crud_resource(crud)
```

## Creating a DSL Processor

```python
class MyProcessor(BaseProcessor):
    def __init__(self, config_value: str, name: str | None = None):
        super().__init__(name)
        self._config = config_value

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        # transform body
        exchange.in_message.set_body(transformed)
```

Add fluent method to `RouteBuilder`:
```python
def my_step(self, config: str) -> "RouteBuilder":
    self._processors.append(MyProcessor(config_value=config))
    return self
```

## Adding a New Integration Client

1. Create settings in `src/core/config/`:
```python
class MyServiceSettings(BaseSettingsWithLoader):
    yaml_group: ClassVar[str] = "my_service"
    model_config = SettingsConfigDict(env_prefix="MY_SERVICE_", extra="forbid")
    host: str = Field("localhost")
    enabled: bool = Field(False)

my_service_settings = MyServiceSettings()
```

2. Add to `Settings` in `src/core/config/settings.py`

3. Create client in `src/infrastructure/clients/`

## Testing

```bash
# Unit tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=html

# Specific test
pytest tests/test_my_feature.py -k test_name
```

## Streamlit Dashboard

```bash
streamlit run src/entrypoints/streamlit_app/app.py --server.port 8501
```

Set `API_BASE_URL` env var to point to the FastAPI backend.
