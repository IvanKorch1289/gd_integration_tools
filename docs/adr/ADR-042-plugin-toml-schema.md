# ADR-042: `plugin.toml` — манифест плагина V11 (R1.2)

- **Статус:** proposed
- **Дата:** 2026-05-04
- **Фаза:** R1 Foundation (V11 — domain-agnostic core re-frame)
- **Автор:** v11-architect

## Контекст

V11.1 фиксирует контракт «ядро ↔ плагин»: плагины поставляются только
in-tree (`extensions/<name>/`), исполняются через runtime
capability-gate, расширяют DSL только публичными точками
(Processor/Source/Sink/Action/Schema), а не новыми YAML-keywords.

Текущий манифест Wave 4.4 (`src/services/plugins/manifest.py`,
`PluginManifest`) описан в YAML и не покрывает ключевые контрактные
поля V11:

| Поле | Wave 4.4 (`plugin.yaml`) | V11.1 цель |
|---|---|---|
| name | ✅ | ✅ |
| version | ✅ | ✅ |
| python_requires | ✅ | ❌ (ядро гарантирует Python; плагины не привязаны к minor) |
| requires_core | ❌ | ✅ (semver-compat с ядром) |
| capabilities[] | ❌ | ✅ (sandbox runtime-gate) |
| tenant_aware | ❌ | ✅ (явная декларация) |
| provides[] (унифицированный inventory) | частично (actions/repositories/processors) | ✅ (+ sources/sinks/schemas) |
| entry_class | ✅ | ✅ |
| config | ✅ | ✅ + опц. `config_schema` |

Параллельно команда хочет:

1. Унифицировать формат с экосистемой Python-инструментов
   (`pyproject.toml`, `uv.lock`, `ruff.toml`) — все TOML.
2. Получить детерминированный парсер (`tomllib` в stdlib с 3.11)
   без YAML-duck-typing-сюрпризов (`yes`/`no` → bool, мульти-док,
   anchors).
3. Иметь авто-сгенерированный JSON-Schema для IDE-подсказок
   и валидации в CI без подключения pydantic в каждом тесте.

Wave 4 entry_points-discovery (`importlib.metadata`) удаляется (V11.1):
loader сканирует только `extensions/<name>/plugin.toml`. Это снимает
необходимость поддерживать «два пути» (entry_point vs file-based)
и упрощает `PluginLoader`.

## Рассмотренные варианты

- **Вариант 1 — оставить YAML (`plugin.yaml`), расширить полями
  V11.1.** Плюсы: ноль миграции существующих манифестов
  (`plugins/example_plugin/plugin.yaml`). Минусы: продолжение
  YAML-сюрпризов в строгой schema; YAML-парсер (`PyYAML`) — отдельная
  зависимость; рассогласование с экосистемой Python-инструментов.

- **Вариант 2 — JSON (`plugin.json`).** Плюсы: stdlib-парсер, строгая
  грамматика. Минусы: не поддерживает комментарии (а они нужны
  в манифестах для пояснений capability-scope'ов и feature-flag'ов);
  громоздкий для человека.

- **Вариант 3 — TOML (`plugin.toml`).** Плюсы: stdlib-парсер
  (`tomllib`); поддержка комментариев; конвенция Python-экосистемы;
  естественные таблицы (`[[capabilities]]`, `[provides]`); нет
  duck-typing. Минусы: миграция существующих `plugin.yaml`
  (~1 файл сегодня) + написание TOML-loader'а.

- **Вариант 4 — Pydantic-only API (плагин строит манифест в коде).**
  Плюсы: типобезопасно, без файлового формата. Минусы: ломает
  принцип «декларативный inventory ядру до импорта плагина»
  (capability-gate должен проверить разрешения **до** активации
  плагина, иначе capability-фасады не успеют ограничить ресурсы).
  Не подходит.

## Решение

Принят **Вариант 3 — `plugin.toml`** как единственный формат
манифеста V11. YAML-loader сохраняется как **deprecated shim**
на ≥ 1 minor-цикл (правило API-stability из V11.1) с warning при
load; затем удаляется.

### Структура `plugin.toml`

```toml
# extensions/credit_pipeline/plugin.toml
name = "credit_pipeline"
version = "1.0.0"
# SemVer-spec, валидируется при load; mismatch → плагин пропускается
# с явной ошибкой и не валит весь PluginLoader.
requires_core = ">=0.2,<0.3"
# Dotted path к BasePlugin-наследнику. Импорт делает PluginLoader
# после проверки requires_core и capabilities; при ImportError
# плагин помечается как failed.
entry_class = "extensions.credit_pipeline.plugin.CreditPipelinePlugin"
# Объявляет, что плагин сознательно работает с TenantContext
# в каждом DSL-step. Если false — ядро гарантирует, что плагин
# не получит TenantContext-API (фасад вернёт NoTenantError).
tenant_aware = true
description = "Кредитный конвейер: БКИ + СМЭВ + ЦБ"
# Опц. путь к JSON-Schema для блока [config]. Валидация в load().
config_schema = "schemas/credit_pipeline_config.schema.json"

# ─── Runtime capabilities (sandbox gate) ──────────────────────────
# Каждый ресурс-вызов фасада проходит через CapabilityGate.
# Capability вне декларации → CapabilityDeniedError.
# Полное определение каталога capabilities — см. ADR R1.1.

[[capabilities]]
name = "db.read"
scope = "credit_db"

[[capabilities]]
name = "db.write"
scope = "credit_db"

[[capabilities]]
name = "secrets.read"
scope = "vault://credit/*"

[[capabilities]]
name = "net.outbound"
scope = "*.cbr.ru"

[[capabilities]]
name = "mq.publish"
scope = "credit.events.*"

# ─── Декларативный inventory (что регистрирует плагин) ────────────
# Используется для: (1) проверки до активации, что не будет коллизий
# с уже зарегистрированными именами; (2) admin-эндпоинта
# /api/v1/plugins/inventory; (3) DSL-Linter (R2) подсказок.

[provides]
actions = ["credit.score_application", "credit.fetch_bki"]
repositories = ["loan_applications"]
processors = ["bki_normalizer"]
sources = []
sinks = ["smev_sink"]
schemas = ["loan_application_v1"]

# ─── Произвольная конфигурация ────────────────────────────────────
# Передаётся как ctx.config в on_load(); при наличии config_schema —
# валидируется против неё.

[config]
default_timeout_ms = 30000
fallback_provider = "stub"
```

### Pydantic-набросок (V11 target)

> Целевой модуль: `src/services/plugins/manifest_v11.py` (реализован в
> R1-импл-Wave 2026-05-04). `CapabilityRef` живёт в
> `src/core/security/capabilities/` (ADR-044).

```python
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CapabilityRef(BaseModel):
    """Декларация одной capability с опциональным scope-glob."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    """Имя capability из каталога ADR R1.1 (`db.read`, `secrets.read`, ...)."""

    scope: str | None = None
    """Glob или alias-имя (`credit_db`, `vault://credit/*`, `*.cbr.ru`)."""


class PluginProvides(BaseModel):
    """Декларативный inventory плагина."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actions: tuple[str, ...] = ()
    repositories: tuple[str, ...] = ()
    processors: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    sinks: tuple[str, ...] = ()
    schemas: tuple[str, ...] = ()


class PluginManifestV11(BaseModel):
    """Манифест плагина V11 (`extensions/<name>/plugin.toml`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1)
    requires_core: str = Field(min_length=1)
    entry_class: str = Field(min_length=1)
    tenant_aware: bool = False
    description: str | None = None
    config_schema: str | None = None
    capabilities: tuple[CapabilityRef, ...] = ()
    provides: PluginProvides = PluginProvides()
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("requires_core")
    @classmethod
    def _validate_semver_spec(cls, value: str) -> str:
        try:
            SpecifierSet(value)
        except InvalidSpecifier as exc:
            raise ValueError(f"Invalid requires_core spec: {value!r}") from exc
        return value

    def is_compatible_with_core(self, core_version: str) -> bool:
        """Совместим ли плагин с заданной версией ядра."""
        return core_version in SpecifierSet(self.requires_core)


class PluginManifestError(ValueError):
    """Ошибка парсинга / валидации `plugin.toml`."""


def load_plugin_manifest(path: Path | str) -> PluginManifestV11:
    """Прочитать и валидировать `plugin.toml`."""
    file_path = Path(path)
    if not file_path.is_file():
        raise PluginManifestError(f"Manifest not found: {file_path}")
    try:
        raw = tomllib.loads(file_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise PluginManifestError(f"Invalid TOML in {file_path}: {exc}") from exc
    try:
        return PluginManifestV11.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError → wrap
        raise PluginManifestError(
            f"Manifest validation failed for {file_path}: {exc}"
        ) from exc
```

### V0 capability vocabulary (forward-ref на ADR R1.1)

Минимальный набор, нужный R1-демо плагинам. **Полный каталог,
формальная грамматика scope-glob и таблица соответствия фасадам —
в ADR R1.1 (Capability vocabulary).** Здесь — placeholder для
консистентности этого ADR:

| Capability | Scope-форма | Фасад ядра |
|---|---|---|
| `db.read` | DSN-alias из `config_profiles/*.yml` | `DatabaseFacade.session(...)` (read-only) |
| `db.write` | DSN-alias | `DatabaseFacade.session(...)` (rw) |
| `secrets.read` | URI-glob (`vault://<glob>` / `env://<glob>`) | `SecretsFacade.get(...)` |
| `net.outbound` | host-glob (`*.cbr.ru`) | `HTTPFacade.request(...)` / `GRPCFacade.invoke(...)` |
| `fs.read` | path-glob (под `<plugin>/data/*`) | `FSFacade.open(..., mode="r")` |
| `fs.write` | path-glob | `FSFacade.open(..., mode="w")` |
| `mq.publish` | topic-glob | `MQFacade.publish(...)` |
| `mq.consume` | topic-glob | `MQFacade.consume(...)` |
| `cache.read` | namespace-prefix (под `tenant:{id}:plugin:{name}:*`) | `CacheFacade.get(...)` |
| `cache.write` | namespace-prefix | `CacheFacade.set(...)` |

Запрос capability вне списка → `CapabilityDeniedError` с включением
имени плагина, фасада, requested scope; событие пишется в audit.

### JSON-Schema export

CI-цель `make plugin-schema` (после R1-импл) выполняет:

```bash
uv run python -c \
  "from src.services.plugins.manifest_v11 import PluginManifestV11; \
   import json; \
   print(json.dumps(PluginManifestV11.model_json_schema(), indent=2))" \
  > docs/reference/schemas/plugin.toml.schema.json
```

Файл коммитится; gh-pages сервит его как
`https://<repo>.github.io/schemas/plugin.toml.schema.json` для
`# yaml-language-server: $schema=...` подсказок в IDE
(Toml-LSP читает поле `$schema` через комментарий-директиву).

### Migration path (Wave 4.4 YAML → V11 TOML)

1. **Шаг 1 (Wave R1.2.a):** Новый `manifest_v11.py` с TOML-loader
   живёт параллельно с Wave-4.4 `manifest.py` (YAML). PluginLoader
   пытается сначала `plugin.toml`, при отсутствии — fallback на
   `plugin.yaml` с deprecation-warning.
2. **Шаг 2 (Wave R1.2.b):** Скрипт `tools/migrate_plugin_manifest.py`
   конвертирует существующие `plugin.yaml` → `plugin.toml` с
   placeholder-ами `requires_core`/`capabilities`/`tenant_aware`
   (требует ручного дозаполнения после).
3. **Шаг 3 (Wave R1.2.c):** YAML-loader удаляется; `PluginManifest`
   (Wave 4.4 модель) — переезжает в `docs/legacy/` как reference.
4. **Шаг 4 (R3):** В `extensions/<name>/plugin.toml` enforce
   `make plugin-validate` через pre-push gate.

### Lifecycle (без изменений Wave 4)

Порядок вызовов `PluginLoader.discover_and_load()`:

1. Сканирование `extensions/*/plugin.toml`.
2. `load_plugin_manifest(path)` → `PluginManifestV11`.
3. `manifest.is_compatible_with_core(CORE_VERSION)` — несовместимый
   плагин логируется как `[skipped]` и не активируется.
4. **Capability allocation:** для каждой `CapabilityRef` из
   `manifest.capabilities` `CapabilityGate` создаёт scoped-фасад;
   если scope не разрешён политикой ядра — `CapabilityDeniedError`.
5. **Inventory pre-check:** `manifest.provides` сопоставляется с
   уже зарегистрированными actions/repositories/...; коллизия →
   плагин отклоняется (имя уже занято).
6. `import_module(manifest.entry_class)` → instantiate.
7. Wave-4 lifecycle: `on_load → on_register_actions →
   on_register_repositories → on_register_processors`.

## Последствия

- **Положительные:**
  - Декларативный inventory + capability-список читается **до**
    импорта Python-кода плагина → loader может валидировать
    совместимость и капабилити без выполнения `entry_class`.
  - TOML унифицирован с экосистемой Python (pyproject.toml,
    uv.lock); `tomllib` в stdlib — на одну зависимость меньше.
  - `requires_core`-spec даёт явный механизм поддержки
    breaking-change-ов в plugin API через major-bump ядра.
  - `tenant_aware: bool` — простой и явный gate; плагины без
    этого флага гарантированно не получают TenantContext.
  - `config_schema` с JSON-Schema даёт валидацию `[config]`
    в момент load, а не в `on_load` плагина.
- **Отрицательные:**
  - Ломается Wave-4 `entry_points`-discovery — придётся
    мигрировать `plugins/example_plugin/` на in-tree
    `extensions/example_plugin/`. Митигация: keep
    `plugins/example_plugin/` как «legacy entry_points» reference,
    отмеченный deprecated.
  - Дополнительный шаг при разработке плагина: написать
    `plugin.toml` с capabilities-секцией. Митигация: codegen
    `make new-plugin NAME=<x>` (R1-импл).
  - YAML-shim требует тестов на оба формата на ≥ 1 minor-цикл.
- **Нейтральные:**
  - Pydantic v2 `model_config={"extra": "forbid", "frozen": True}`
    унаследован из Wave 4.4 `PluginManifest` — стиль не меняется.
  - JSON-Schema-экспорт встанет в CI как docs-артефакт (по
    аналогии с `make routes`/`make actions`).

## Связанные ADR

- ADR R1.1 (Capability vocabulary) — **dependency**: формальная
  таблица capabilities + scope-grammar; в этом ADR использован
  v0-набор как placeholder.
- ADR-043 (R1.2a route.toml) — **sibling**: маршруты как
  «лёгкие плагины» по тем же правилам.
- ADR-011 (Open-Closed Plugins) — **superseded** этим ADR в части
  поставки (`entry_points` → `extensions/`).
- ADR-022 (Connector SPI) — **связан**: коннекторы остаются
  отдельной registry, но плагин может декларировать новые
  коннекторы через `provides.sources` / `provides.sinks`.
