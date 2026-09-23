# ADR-0337 — Canonical error contract (DomainProblem)

## Статус

**Accepted** (2026-09-23). Закрывает architectural gap "Canonical error
contract" из стратегического анализа 2026-09-22.

## Контекст

Стратегический анализ (timestamp 1790089356160) выявил gap:

> «GraphQL-specific обработчик не заменяет общий контракт. Сейчас
> каждый transport может независимо определять retryability, коды и
> раскрываемые детали.
>
> Нужен объект уровня core:
>
> ```python
> @dataclass(frozen=True, slots=True)
> class DomainProblem:
>     code: str
>     category: ProblemCategory
>     title: str
>     retryable: bool
>     safe_details: Mapping[str, object]
>     correlation_id: str
> ```
>
> Transport adapters должны только преобразовывать его в RFC 9457,
> GraphQL extensions, gRPC Status, SOAP Fault, MCP error или DLQ
> envelope.»

В репо уже есть:

- `src/backend/core/errors.py` — `BaseError` иерархия (NotFoundError,
  AuthenticationError и др.) с `to_dict()` / `grpc_status_code` /
  `soap_fault_code` properties.
- `src/backend/entrypoints/graphql/canonical_errors.py` — GraphQL-specific
  `format_graphql_error` с `extensions.code` + `extensions.category`.

Но:
- `BaseError` — Python exception (raise в коде), а не data structure.
- GraphQL canonical_errors — не transport-neutral (только GraphQL).
- Нет единого ``code`` / ``category`` / ``retryable`` контракта для
  остальных транспортов (REST/RFC 9457, gRPC, SOAP, MCP, DLQ envelope).
- Каждый transport может независимо определять retryability → drift
  между клиентами.

## Решение

Добавить в ``src/backend/core/errors.py`` (additive — не ломает
существующий API):

### 1. ``ProblemCategory`` (8 категорий)

Enum с фиксированным набором категорий. Значения совпадают с
``entrypoints/graphql/canonical_errors.py::ErrorCategory`` для backward
compat с GraphQL-инфраструктурой:

| Category | HTTP default | gRPC code | Retryable |
|---|---|---|---|
| VALIDATION | 422 | INVALID_ARGUMENT (3) | No |
| AUTHENTICATION | 401 | UNAUTHENTICATED (16) | No |
| AUTHORIZATION | 403 | PERMISSION_DENIED (7) | No |
| NOT_FOUND | 404 | NOT_FOUND (5) | No |
| CONFLICT | 409 | ALREADY_EXISTS (6) | No |
| RATE_LIMIT | 429 | RESOURCE_EXHAUSTED (8) | Yes |
| UNAVAILABLE | 503 | UNAVAILABLE (14) | Yes |
| INTERNAL | 500 | INTERNAL (13) | Yes |

### 2. ``DomainProblem`` (frozen dataclass)

```python
@dataclass(frozen=True, slots=True)
class DomainProblem:
    code: str                                          # SCREAMING_SNAKE_CASE
    category: ProblemCategory
    title: str                                         # human-readable
    retryable: bool | None = None                      # explicit override OR None=auto
    status_code: int = 0                               # 0 = auto-derive from category
    safe_details: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    cause: BaseException | None = field(default=None, compare=False, repr=False)
```

Validation в ``__post_init__``:
- ``code`` обязателен и должен быть SCREAMING_SNAKE_CASE.
- ``status_code == 0`` → auto-derive из category.

``is_retryable`` property:
- ``retryable=None`` → category default (UNAVAILABLE/RATE_LIMIT/INTERNAL).
- Explicit True/False → перебивает category default.

### 3. Transport adapters (6 форматов)

Каждый adapter возвращает чистый ``dict`` (без side-effects):

| Adapter | Формат | Ссылка |
|---|---|---|
| ``to_rfc9457()`` | RFC 9457 Problem Details | https://www.rfc-editor.org/rfc/rfc9457 |
| ``to_graphql_extensions()`` | GraphQL extensions dict | совместим с `canonical_errors.py` |
| ``to_grpc_status()`` | (StatusCode, message, details-dict) | gRPC Status + trailing_metadata |
| ``to_soap_fault()`` | SOAP 1.1 Fault envelope | faultcode/faultstring/detail |
| ``to_mcp_error()`` | JSON-RPC 2.0 error (MCP) | code/message/data |
| ``to_dlq_envelope()`` | DLQ envelope | code/category/title/retryable/status_code/correlation_id/details |

### 4. Factory methods

- ``DomainProblem.from_exception(exc, *, correlation_id="")`` — auto-build
  из любого ``BaseException``. Если ``BaseError`` — использует
  ``_BASE_ERROR_TO_CODE`` mapping; иначе generic ``INTERNAL_ERROR``.
- ``DomainProblem.from_base_error(exc, *, category=None, correlation_id="")`` —
  явное преобразование с optional category override.

## Альтернативы (отклонённые)

- **Новый ``src/backend/core/errors/domain_problem.py`` + package split** —
  отклонено: файл errors.py сейчас 732 LOC после добавления, что
  ниже god-module threshold (1000). Split приведёт к over-engineering.
- **Замена BaseError на DomainProblem** — отклонено: BaseError и
  DomainProblem — **разные concerns** (Python exception vs data
  structure). Они complement друг друга: raise ``NotFoundError`` →
  catch → ``DomainProblem.from_exception`` → serialize в 6 транспортов.
- **Pydantic BaseModel вместо dataclass** — отклонено: dataclass быстрее,
  меньше зависимостей, лучше для frozen/slots semantics.
- **Marshmallow / msgspec schema** — отклонено: overkill для in-process
  data structure (нет network serialization requirement).

## Последствия

### Плюсы

- **Single source of truth** для transport-neutral error contract.
- **6 транспортов получают consistent error shape** (RFC 9457/GraphQL/gRPC/
  SOAP/MCP/DLQ).
- **GraphQL backward-compat**: extensions.code/category/retryable —
  те же поля, что в существующем ``canonical_errors.py``.
- **Auto-derive defaults**: status_code/retryable/gRPC-code — из
  category, без дублирования.
- **Frozen + slots**: thread-safe, hashable, минимальный overhead.

### Ограничения

- **safe_details — user responsibility**: gate не валидирует, что
  details не содержат PII/credentials. Контрактный docstring требует
  "non-sensitive context only"; нужен отдельный audit-tool для этого
  (W11 P1+ backlog).
- **gRPC adapter возвращает int код + tuple**: потребляющий код должен
  сам импортировать ``grpc.StatusCode`` enum — это intentional, чтобы
  core/errors.py не зависел от grpc (зависимость только в transport
  adapters).
- **MCP JSON-RPC codes — кастомные** (negative integers в диапазоне
  -32000/-32999 для application errors). Документировано в adapter.

### Backward compat

- Существующие классы (``BaseError``, ``NotFoundError`` и др.) и
  ``build_error_envelope`` работают без изменений.
- Добавлены 2 новых symbol в ``__all__``: ``DomainProblem``,
  ``ProblemCategory``. Существующие импорты не сломаны.

## Verification

| Gate | Команда | Результат |
|---|---|---|
| compileall | `python -m compileall -q src/ extensions/ scripts/ tools/ tests/ testkit/` | EXIT 0 |
| check_python3_syntax | `python tools/checks/check_python3_syntax.py --root .` | EXIT 0 |
| ruff | `python -m ruff check src/backend/core/errors.py tests/...` | All checks passed |
| pytest (DomainProblem) | `python -m pytest tests/unit/core/test_w11_p0_4_domain_problem.py` | 74/74 passed |
| pytest (back-compat) | `python -m pytest tests/unit/core/test_errors_focused.py` | 43/43 passed |
| real-world smoke | `DomainProblem.from_exception(NotFoundError(...))` + 6 adapters | OK |

## Файлы

- `src/backend/core/errors.py` — extended (289 → 732 LOC, 13 → 15 symbols)
- `tests/unit/core/test_w11_p0_4_domain_problem.py` — 74 tests (новый)
- `tests/unit/core/test_errors_focused.py` — обновлён (13 → 15 symbols)
- `docs/adr/INDEX.md` — обновлён (129 → 130 ADRs)

## Использование

```python
from src.backend.core.errors import DomainProblem, ProblemCategory, NotFoundError

# Direct construction (cross-protocol error):
problem = DomainProblem(
    code="ORDER_NOT_FOUND",
    category=ProblemCategory.NOT_FOUND,
    title="Order not found",
    safe_details={"order_id": "123"},
    correlation_id="corr-abc",
)

# Transport-specific serialization:
rfc9457 = problem.to_rfc9457(instance="/orders/123")      # REST
graphql = problem.to_graphql_extensions()                  # GraphQL
grpc = problem.to_grpc_status()                            # gRPC (tuple)
soap = problem.to_soap_fault()                             # SOAP
mcp = problem.to_mcp_error()                               # MCP / JSON-RPC
dlq = problem.to_dlq_envelope()                           # DLQ topic/stream

# From BaseError (raise в коде → DomainProblem для serialization):
try:
    raise NotFoundError(message="Order not found")
except BaseError as exc:
    problem = DomainProblem.from_exception(exc, correlation_id="corr-xyz")
    return JSONResponse(problem.to_rfc9457(), status_code=problem.status_code)
```

## Ссылки

- ADR-0335, ADR-0336 — W11 P0-2/P0-3 (configuration matrix gates)
- ADR-0334 — fact-check master state
- RFC 9457 — Problem Details for HTTP APIs
- GraphQL Error extensions — https://spec.graphql.org/October2021/#sec-Errors.Error-Result-Format
- gRPC Status codes — https://grpc.github.io/grpc/core/md_doc_statuscodes.html
- JSON-RPC 2.0 spec — https://www.jsonrpc.org/specification
- MCP error envelope — Model Context Protocol spec (2026-09)
- PROGRESS_LEDGER: `docs/roadmap/PROGRESS_LEDGER.md`
