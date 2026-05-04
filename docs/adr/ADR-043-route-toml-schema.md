# ADR-043: `route.toml` — манифест маршрута V11 (R1.2a)

- **Статус:** proposed
- **Дата:** 2026-05-04
- **Фаза:** R1 Foundation (V11 — domain-agnostic core re-frame)
- **Автор:** v11-architect

## Контекст

V11.1a фиксирует, что **маршруты — это «лёгкие плагины»**: тот же
`extensions/`-стиль изоляции, тот же capability-gate, но без
Python-кода — только декларация (`route.toml` + один или несколько
`*.dsl.yaml`). Это нужно, чтобы:

1. Одна команда могла поставлять интеграцию **без написания
   Python-плагина** — только YAML с pipeline + TOML-манифест.
2. Loader мог проверить совместимость route с ядром и плагинами
   **до** парсинга YAML — `requires_core` / `requires_plugins`-spec
   работают тем же путём, что `requires_core` в `plugin.toml`
   (см. ADR-042).
3. Hot-reload route проходил через тот же `watchfiles.awatch`-cycle
   (ADR-041), что и `dsl_routes/*.yaml` сегодня — но с отдельным
   manifest, который не перезагружается каждый раз, когда поменялся
   pipeline.

Текущее положение:

- DSL-маршруты лежат в `dsl_routes/` (см.
  `src/core/config/dsl.py::DSLSettings.routes_dir`), формат —
  плоские `*.yaml` / `*.dsl.yaml`. Никаких метаданных, никаких
  capability-деклараций — capability-checks привязаны к `Source`/
  `Sink`/`Processor` глобально.
- Параллельно есть `config/routes/imported/` и `config/routes/proxy/`
  (Wave 24 ImportGateway / W14 ProxyPassthrough); это
  ad-hoc-каталоги без manifest'а.
- DSL-движок (`src/dsl/builder.py`, 3118 LOC) сегодня монолит,
  который **не различает** routes по «происхождению» (in-tree
  legacy vs плагин vs imported); admin-эндпоинты `/api/v1/dsl_routes`
  отдают плоский список без группировки.

V11.1a требует ввести явный manifest и единообразный layout
`routes/<name>/`:

```
routes/credit_pipeline/
├── route.toml                # V11 manifest
├── pipeline.dsl.yaml         # основной pipeline
└── notify_cascade.dsl.yaml   # доп. fragment
```

## Рассмотренные варианты

- **Вариант 1 — оставить плоский `dsl_routes/*.yaml`, метаданные
  встроить в YAML.** Плюсы: zero миграция. Минусы: смешивание
  manifest с pipeline-семантикой; невозможно валидировать
  `requires_plugins` до парсинга всего YAML; YAML-anchors/aliases
  делают строгую schema хрупкой.

- **Вариант 2 — `route.json` рядом с `*.dsl.yaml`.** Плюсы:
  stdlib-парсер. Минусы: нет комментариев (а они нужны для пояснения
  feature-flag поведения и tags); неконсистентно с `plugin.toml`
  из ADR-042.

- **Вариант 3 — `route.toml` + один или несколько `*.dsl.yaml`
  в каталоге `routes/<name>/`.** Плюсы: симметрично с
  `plugin.toml` (одинаковый стек tomllib + pydantic); manifest
  читается до YAML; естественная поддержка multi-file routes
  (главный pipeline + sub-fragments). Минусы: новая директория
  + миграция legacy `dsl_routes/*.yaml` (постепенная, без жёсткого
  deadline по V11.1a).

- **Вариант 4 — единый `extensions/<name>/plugin.toml` + YAML
  внутри.** Плюсы: один формат на всё. Минусы: ломает разделение
  «плагин с кодом» vs «декларативный route» — V11.1a явно
  разделяет их (cap-vocabulary одинаковая, lifecycle разный:
  у route нет `entry_class`, нет `on_load`-Python-хуков).

## Решение

Принят **Вариант 3 — `routes/<name>/route.toml` + `*.dsl.yaml`**.
`dsl_routes/*.yaml` сохраняется как **legacy путь** на ≥ 1
minor-цикл с deprecation-warning при load (то же правило
API-stability, что в ADR-042).

### Структура `route.toml`

```toml
# routes/credit_pipeline/route.toml
name = "credit_pipeline"
version = "1.0.0"
# SemVer-spec совместимости с ядром (см. ADR-042).
requires_core = ">=0.2,<0.3"
# SemVer-spec'ы плагинов, чьи procesor/source/sink/action использует
# pipeline. Loader проверяет до парсинга YAML — ошибка спецификатора
# или отсутствующий плагин дают ясный fail без обращения к pipeline.
[requires_plugins]
credit_pipeline = ">=1.0,<2.0"
bki_connector = ">=0.4,<1.0"

# Объявляет, что pipeline сознательно работает в TenantContext.
tenant_aware = true

# Опц. feature-flag — управление включением маршрута без удаления
# файла. Принимает: булево, или ENV-имя (читается через ядро),
# или dotted-path в IFeatureFlagProvider (R3 OpenFeature).
feature_flag = "ROUTE_CREDIT_PIPELINE_ENABLED"

# Тэги для admin-grouping и DSL-Linter.
tags = ["credit", "production", "tier-1"]

description = "Кредитный конвейер: вход → BKI → СМЭВ → ЦБ → DLQ"

# Список pipeline-файлов в порядке загрузки. Главный pipeline —
# первый; остальные — fragments (notify_cascade, error_branch).
pipelines = ["pipeline.dsl.yaml", "notify_cascade.dsl.yaml"]

# Capabilities должны быть подмножеством объединения capabilities
# requires_plugins'ов (ядро проверяет инвариант): route не может
# запросить больше, чем ему дают плагины.

[[capabilities]]
name = "db.read"
scope = "credit_db"

[[capabilities]]
name = "net.outbound"
scope = "*.cbr.ru"

[[capabilities]]
name = "mq.publish"
scope = "credit.events.*"
```

### Pydantic-набросок (V11 target)

> Целевой модуль: `src/services/routes/manifest_v11.py` (реализован в
> R1-импл-Wave 2026-05-04). `RouteLoader` в `src/services/routes/loader.py`.

```python
from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.security.capabilities import CapabilityRef  # ADR-044


class RouteManifestV11(BaseModel):
    """Манифест маршрута V11 (`routes/<name>/route.toml`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1)
    requires_core: str = Field(min_length=1)
    requires_plugins: dict[str, str] = Field(default_factory=dict)
    """Mapping plugin_name → SemVer-spec."""
    tenant_aware: bool = False
    feature_flag: str | bool | None = None
    """True/False — статически включён/выключен; str — имя ENV или
    dotted-path к FeatureFlagProvider."""
    tags: tuple[str, ...] = ()
    description: str | None = None
    pipelines: tuple[str, ...] = Field(min_length=1)
    """Список path'ей `*.dsl.yaml` относительно `routes/<name>/`."""
    capabilities: tuple[CapabilityRef, ...] = ()

    @field_validator("requires_core")
    @classmethod
    def _validate_core_spec(cls, value: str) -> str:
        try:
            SpecifierSet(value)
        except InvalidSpecifier as exc:
            raise ValueError(f"Invalid requires_core spec: {value!r}") from exc
        return value

    @field_validator("requires_plugins")
    @classmethod
    def _validate_plugin_specs(cls, value: dict[str, str]) -> dict[str, str]:
        for plugin_name, spec in value.items():
            try:
                SpecifierSet(spec)
            except InvalidSpecifier as exc:
                raise ValueError(
                    f"Invalid requires_plugins spec for {plugin_name!r}: "
                    f"{spec!r}"
                ) from exc
        return value

    def is_compatible_with_core(self, core_version: str) -> bool:
        return core_version in SpecifierSet(self.requires_core)

    def missing_plugins(
        self, available: dict[str, str]
    ) -> dict[str, str]:
        """Возвращает несовместимые / отсутствующие плагины.

        ``available`` — `{plugin_name: installed_version}`.
        Возвращает `{plugin_name: required_spec}` для тех, что
        отсутствуют или не подходят по spec.
        """
        missing: dict[str, str] = {}
        for plugin_name, spec in self.requires_plugins.items():
            installed = available.get(plugin_name)
            if installed is None or installed not in SpecifierSet(spec):
                missing[plugin_name] = spec
        return missing


class RouteManifestError(ValueError):
    """Ошибка парсинга / валидации `route.toml`."""


def load_route_manifest(path: Path | str) -> RouteManifestV11:
    """Прочитать и валидировать `route.toml`."""
    file_path = Path(path)
    if not file_path.is_file():
        raise RouteManifestError(f"Manifest not found: {file_path}")
    try:
        raw = tomllib.loads(file_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RouteManifestError(f"Invalid TOML in {file_path}: {exc}") from exc
    try:
        return RouteManifestV11.model_validate(raw)
    except Exception as exc:
        raise RouteManifestError(
            f"Manifest validation failed for {file_path}: {exc}"
        ) from exc
```

### Lifecycle (RouteLoader)

`RouteLoader` живёт в `services/routes/loader.py` (R1-импл) и
вызывается из lifespan приложения после `PluginLoader`:

```
on_load    → сканирование `routes/*/route.toml`
register   → проверки: requires_core, requires_plugins, capabilities
             ⊆ union(plugins.capabilities), уникальность name
enable     → если feature_flag=true (или resolved через провайдера) —
             зарегистрировать pipeline'ы в DSL-engine
hot-reload → watchfiles.awatch на `routes/`; при изменении
             route.toml — full re-register; при изменении
             *.dsl.yaml — только pipeline-reload (manifest cache)
disable    → отозвать DSL-регистрации, оставить manifest в реестре
unregister → удалить manifest из реестра
on_unload  → graceful (вызывается из shutdown)
```

**Ошибочный route не валит остальные:** при load-error
(invalid TOML / missing plugin / capability-超подмножество)
`RouteLoader` логирует ошибку, помечает route как `failed`,
продолжает остальные. Admin-эндпоинт `/api/v1/routes/inventory`
показывает status (`enabled` / `disabled` / `failed` + reason).

### Hot-reload (через ADR-041 watchfiles)

`watchfiles.awatch` следит за `routes/` с `debounce =
DSLSettings.hot_reload_debounce_ms`:

| File-event | Что перезагружается |
|---|---|
| `routes/<name>/route.toml` (modify) | full re-register: re-load manifest, re-check capabilities, re-register pipelines |
| `routes/<name>/*.dsl.yaml` (modify) | только pipeline-reload (manifest cache переиспользуется) |
| `routes/<name>/route.toml` (delete) | unregister route + cascade deactivate pipelines |
| `routes/<NEW>/route.toml` (create) | full register |

Это делит «дешёвый» reload (правка YAML) и «дорогой» (правка
manifest, проверка совместимости заново) — нагрузка на CPU
на hot-reload падает.

### Testkit fixture

Пакет `gd-integration-tools-testkit` (R1) поставляет fixture
для запуска одного route без поднятия compose:

```python
# testkit/fixtures/routes.py
import pytest

@pytest.fixture
def loaded_route():
    """Загружает один route из tmpdir, возвращает `LoadedRoute`."""

    def _factory(
        manifest_toml: str,
        pipelines: dict[str, str],
        plugins: dict[str, RegisteredPlugin] | None = None,
    ) -> LoadedRoute:
        ...

    return _factory


# usage
def test_credit_pipeline_smoke(loaded_route):
    route = loaded_route(
        manifest_toml=...,
        pipelines={"pipeline.dsl.yaml": ...},
        plugins={"bki_connector": fake_bki_plugin()},
    )
    result = route.invoke({"app_id": 42})
    assert result.status == "scored"
```

Compose-free smoke-тест занимает < 200 мс — позволяет команде
плагина писать e2e без всей инфраструктуры.

### JSON-Schema export

CI-цель `make route-schema` (после R1-импл):

```bash
uv run python -c \
  "from src.services.routes.manifest_v11 import RouteManifestV11; \
   import json; \
   print(json.dumps(RouteManifestV11.model_json_schema(), indent=2))" \
  > docs/reference/schemas/route.toml.schema.json
```

### Migration path

1. **Шаг 1 (Wave R1.2a.a):** `RouteLoader` v0 — сканирует
   `routes/<name>/`; при отсутствии каталога — silent (только
   `dsl_routes/` legacy путь работает).
2. **Шаг 2 (Wave R1.2a.b):** Скрипт
   `tools/migrate_dsl_routes_to_v11.py` оборачивает каждый
   `dsl_routes/<x>.yaml` в каталог `routes/<x>/` с скелетом
   `route.toml` (placeholder-capabilities; ручное дозаполнение).
3. **Шаг 3 (Wave R1.2a.c):** Новые routes пишутся только в
   V11-формате; legacy `dsl_routes/*.yaml` сохраняется до Wave R1
   завершения.
4. **Шаг 4 (R3):** legacy путь удаляется; `DSLSettings.routes_dir`
   deprecated alias на `routes/` через warning + auto-migration
   stub.

## Последствия

- **Положительные:**
  - Manifest читается до YAML → loader может отвергнуть route
    по `requires_core` / `requires_plugins` без парсинга pipeline.
  - Capability-gate route наследует тот же механизм, что плагины
    (см. ADR-042) — без отдельной runtime-логики.
  - `feature_flag` в manifest даёт декларативное вкл./выкл.
    маршрута без удаления файла; интегрируется с R3 OpenFeature.
  - Hot-reload получает «дешёвый/дорогой» путь — pipeline-правка
    не запускает полную re-validate manifest'а.
  - Группировка по `tags` упрощает admin-эндпоинт
    `/api/v1/routes/inventory` и DSL-Linter.
- **Отрицательные:**
  - Переход с плоского `dsl_routes/<x>.yaml` на каталог
    `routes/<x>/` ломает существующие cli-привычки
    (`make routes` отображает оба источника, но grep по
    одному пути теперь не покрывает route).
  - Дублирование информации: `tags` / `description` есть и в
    manifest, и могут быть в комментариях YAML — дисциплина
    «manifest источник истины» нужна.
  - `requires_plugins` создаёт hard-graph между routes и
    плагинами; loader должен загружать в правильном порядке
    (плагины сначала). Митигация: V11.1a уже фиксирует, что
    `RouteLoader` идёт **после** `PluginLoader`.
- **Нейтральные:**
  - V11.1a допускает несколько `*.dsl.yaml` под одним route —
    `pipelines = [...]`; порядок задаёт manifest. Это новое
    поведение по сравнению с плоским `dsl_routes/`, где каждый
    `*.yaml` = один route.

## Связанные ADR

- ADR-042 (R1.2 plugin.toml) — **sibling**: тот же стек tomllib
  + pydantic + capability-gate; `CapabilityRef` переиспользуется.
- ADR R1.1 (Capability vocabulary) — **dependency**: формальный
  каталог + scope-grammar.
- ADR-041 (FS-watcher unification, watchfiles) — **dependency**:
  hot-reload routes идёт через тот же `awatch`-cycle.
- ADR-031 (DSL durable workflows) — **связан**: workflow-routes
  будут описаны тем же manifest'ом; backend-смена (Wave D
  Temporal) не затрагивает manifest.
- ADR-005 (DSL engine) — **связан**: route в pipelines использует
  тот же DSL `RouteBuilder` без изменений.
