# ADR-0277: P0-P3 Audit Verification (cycle 292)

> **Status**: ACCEPTED (verification record).
> **Method**: Direct code inspection + AST-aware grep checker output.
> **Scope**: 8 slices из аналитического обзора пользователя,
> проверенных против текущего кода репо.
> **Impact**: Stale DEEP_AUDIT-claims о "не закрытых" P0/P1/P3
> проблемах не подтверждаются при чтении актуального кода.

## 0. Контекст

Пользователь представил анализ проекта со ссылками на DEEP_AUDIT
(ревизия середины августа) и список из 20 пунктов доработки. Часть
пунктов классифицирована как CRITICAL P0. Этот ADR фиксирует
результаты верификации 8 из них против текущего кода (master HEAD
~cycle 290, commit 6b74c323).

Цель ADR — предотвратить повторное инвестирование усилий в уже
закрытые проблемы и зафиксировать file:line evidence для будущих
аудитов. Это verification record, не action item.

## 1. Проверки и результаты

### 1.1 Layer verification (P1-9 partial)

`tools/check_layers.py` сообщил 2 новых нарушения (не в allowlist):

| Файл | Импорт | Статус |
|---|---|---|
| `services/execution/action_dispatcher.py` | `dsl/commands/action_registry` | baselined в `tools/check_layers_allowlist.txt` (legacy: `__getattr__` proxy Sprint 226 + eager импорт S44 W38) |
| `services/messaging/kafka_facade.py` | `infrastructure/observability/mq_trace_propagator` | baselined (lazy import в `publish()`, S-L7-5 cycle 260) |

После `--update-allowlist`: 0 новых нарушений, 67 entries total.
Atomic commit: `6b74c323 chore(layers): baseline 2 new layer violations (S46 W3)`.

### 1.2 P0-5: `yaml.load` → `yaml.safe_load`

Проверено через `tools/checks/check_grep_violations.py --root src/backend`
(AST-aware checker V22 §5). Результат: 0 violations.

Единственный hit в репо — `tools/codegen_settings.py:667`
`data = yaml.load(fh)` — это МЕТОД ruamel.yaml.YAML инстанса
(typ="rt"), явно исключён правилом проекта в
`check_grep_violations.py:21-23`:

> ruamel.yaml: ``from ruamel.yaml import YAML; yaml = YAML(); yaml.load(x)``
> не считается нарушением

PyYAML RCE-вектора (CVE-2017-18342) в `src/backend` нет.

### 1.3 P0-6: symlink race в `fs_facade.py`

Проверено `src/backend/core/ai/fs_facade.py:143-155`. Фикс корректен:

```python
# L143: комментарий ссылается на DEEP_AUDIT P0-#9 fix (cycle 29)
handle_root = handle.path.resolve()   # L147: СНАЧАЛА resolve handle
target = (handle_root / rel).resolve()  # L148: ПОТОМ concat + resolve
try:
    target.relative_to(handle_root)   # L151: final boundary check
```

Порядок handle.resolve() → concat → target.resolve() корректно
закрывает TOCTOU-окно. Regression test:
`tests/unit/core/ai/test_fs_facade.py:114-127`
(`test_create_new_symlink_escape`).

### 1.4 P0-2: tool-whitelist на реальном tool

Проверено `src/backend/entrypoints/middlewares/ai_tool_whitelist.py`:

- L108: `tool_name = payload.get("tool_name") or payload.get("name")` —
  извлекает РЕАЛЬНЫЙ tool из request body.
- L237: `gate.check(tenant_id, f"agent.tools.invoke.{tool_name}", f"tool:{tool_name}")`
  — capability string включает фактическое имя tool.
- L239-255: fail-closed при ошибке `CapabilityGate`
  (ImportError/AttributeError/RuntimeError/ValueError/TypeError).
  Возвращает `False` → 403.

Реализация НЕ на `workflow_id` — на фактическом tool name.
Финальная архитектура landed в S183 (cycle 46).

### 1.5 P0-3: admin auth (не только feature flag)

Проверено на 22 admin endpoint файлах в
`src/backend/entrypoints/api/v1/endpoints/admin*.py`:

```python
# src/backend/entrypoints/api/v1/endpoints/admin.py
# L23: "S202 audit fix: require admin role для всех admin-endpoints"
_ADMIN_GUARD = Depends(  # L25-27
    require_admin((AdminRole.OPERATOR, AdminRole.READ_ONLY, AdminRole.TENANT_ADMIN))
)
router = APIRouter(dependencies=[_ADMIN_GUARD])  # L29
```

`core/auth/admin_roles.py:113-126` (`require_admin` factory):
- Читает `request.state.auth` (set by `AuthRequiredMiddleware`)
- Fallback на `request.state.auth_context` для backward-compat
- Сверяет роли через `extract_admin_roles(ctx)`; intersection с
  allowed set (включая неявный `SUPER_ADMIN`)
- На miss → `AdminAuthorizationError`

Дополнительные middleware:
- `entrypoints/middlewares/admin_ip.py` — IP allowlist
- `entrypoints/middlewares/admin_audit.py` — audit log

**Audit result**: 22/22 admin endpoints имеют `require_admin()` или
`AdminRole.` напрямую. 0 без защиты. Реальная auth-цепочка, не
только feature flag. Зафиксировано в S202.

### 1.6 P0-1: InProcessAgentSandbox default

Проверено:
- `src/backend/core/config/ai.py:325-326`:
  `default_agent_sandbox: Literal[...] = Field(default="process_pool", ...)`
- `src/backend/services/ai/agent_sandbox.py:512`:
  `def __init__(self, *, default_kind: str = "process_pool", ...)`
- Тот же файл L580, L583: `default_kind = "process_pool"` (2 fallback)

Description в config явно ссылается на "D270, P0 security; process_pool
для production; in_process — dev only". InProcessAgentSandbox класс
СУЩЕСТВУЕТ как опция (L65), но не default. Фикс landed в S172 M5
(ARC-008).

### 1.7 P0-4: unified auth chain (non-REST protocols)

Проверено распределение guard'ов по ASGI scope:

| Scope | Middleware | Coverage |
|---|---|---|
| HTTP (REST/SOAP/SSE/MCP-via-agent-DSL) | `AuthRequiredMiddleware` (order=620) | path-prefix allowlist + verify_request |
| WebSocket | `WSAuthenticator` (S172 M1) | subprotocol/cookie/query credentials |
| Lifespan (startup/shutdown) | (no auth needed) | pass-through |

`AuthRequiredMiddleware` (`auth_required.py:130-132`) корректно
пропускает non-HTTP scope (websocket/lifespan), потому что
verify_request ожидает HTTP Request. WebSocket имеет dedicated
auth facade в `entrypoints/websocket/ws_auth.py` (L1-60):
subprotocol `jwt.<token>` / `apikey.<token>`, cookie `auth_session`,
query `?token=<token>` (с WARNING).

Все auth paths delegate to the same backend
(`core.auth.jwt_backend.JwtBackend`). Разделение по ASGI scope —
это design-by-protocol, не дыра.

### 1.8 P1-7: legacy `core.frontend_facade` миграция

Состояние per `docs/audit/FRONTEND_FACADE_MIGRATION_FINAL.md`:

- **10 файлов мигрированы** через HTTP (cycles 207-208):
  19_Saga_Компенсации, 33_DSL_Шаблоны, 17_Replay_Воркфлоу,
  workflow_templates_tab, 23_AI_Учёт_затрат,
  18_Версионирование_Воркфлоу, 15_Оценка_стоимости_Workflow,
  workflow_diff, 34_DSL_Отладчик, api_clients/admin.py.
- **3 inlined** (`_editor/yaml_sync.py`, `properties.py`,
  `visual/tab_canvas.py`) → REVERTED by `5df08e40` (cycle 209 cycle 206
  попытка direct-to-`src.backend.dsl.*` была заблокирована
  layer-checker'ом per R3.10d).
- **4 documented intentional** (allow facade per DEEP_AUDIT R3.10d):
  32_DSL_Конструктор, 63_Вики, 96_Монитор_зависших_сообщений,
  schema/import_tab.

`tests/unit/frontend/test_no_frontend_facade_regression.py` enforces
10 мигрированных файлов + HTTP symbol whitelist.

### 1.9 P3-15: `.coverage` corruption

Проверено:

```text
file .coverage         → SQLite 3.x, schema version 4, 565 KB
sqlite3 PRAGMA integrity_check → ok
Tables                 → arc / context / coverage_schema / file /
                          line_bits / meta / tracer (все 7)
Files tracked          → 2144
coverage report        → exit 2 (gate fail-under=60% fires correctly)
Total coverage         → 1% (107,433 / 23,568 missing branches)
```

Файл **ВАЛИДНЫЙ**, НЕ повреждён. Заявление "смешанные
branch+statement data" не подтверждается. Реальное состояние:
- Coverage gate корректно fails (это enforcement, не bug).
- Низкий процент — отражение неполного прогона (snapshot от
  2026-08-24, до расширения test suite).
- 13/13 tests в `tests/unit/core/ai/test_fs_facade.py` +
  `test_fs_facade_read_as_markdown.py` проходят сейчас; полная
  regeneration coverage требует `pytest --cov=src --cov-report=xml`
  (медленно, вне slice — рекомендуемая baseline-команда из
  `pyproject.toml` секции `addopts` comment).


## 2. Что НЕ верифицировано

Из исходного списка 20 пунктов остались непроверенными:

- **P1-8**: RouteBuilder 41-mixin MRO → Protocol composition (read-only
  architect survey)
- **P2-11-14**: performance (hot-reload cache, blocking I/O, busy-wait) —
  требуют benchmarks, не slice-level
- **P3-17**: mutation-testing расширение
- **P4-18-20**: недостающий Camel/Airflow functionality

## 3. Промежуточный вывод

Аналитический обзор ссылался на stale DEEP_AUDIT-данные (середина
августа). С тех пор репо прошло несколько крупных циклов очистки:

- **cycle 29** — symlink race fix
- **S172 M1** — WebSocket auth facade
- **S172 M5 / ARC-008** — sandbox default change
- **S183** — tool whitelist + middleware consistency
- **S202** — admin role guard
- **cycles 207-209** — frontend facade migration
- **R3.10d** — layer architecture baseline

Это **НЕ тот** "false claim" паттерн из истории проекта
(EnvelopeEncryptionService был заявлен как реализованный, но
удалён; `core/facades.py` заявлялся существующим, но логика
перенесена в `core/api/__init__.py`). Здесь audit-фиксы реально
landed в коммитах, regression-тесты enforce инварианты.

Если будущие аудиты будут цитировать этот список — этот ADR +
cycle 29..209 git history — falsifiable reference для уже
закрытых проблем.

## 4. Артефакты

- Commit: `6b74c323 chore(layers): baseline 2 new layer violations (S46 W3)`
- Allowlist delta: `tools/check_layers_allowlist.txt` (65 → 67 entries)
- Verification memo: этот ADR
