# Testkit — Public API for Plugin Authors

**K5 S19 W3 · S-L10-1**

`src.testkit` provides a stable public API for writing unit tests against
GD Integration Tools plugins and extensions. All symbols documented here
are covered by a stability guarantee — breaking changes require a major
version bump.

```{contents}
:local:
:depth: 2
```

---

## Installation

The testkit is included in the `testkit` extra of `gd_advanced_tools`:

```bash
pip install gd_advanced_tools[testkit]
```

Or add it as a development dependency:

```toml
# pyproject.toml
[project.optional-dependencies]
testkit = [
    "gd_advanced_tools[testkit]",
]
dev = [
    "gd_advanced_tools[testkit,workflow]",
]
```

---

## RouteRunner

Execute DSL routes in isolation without a live ASGI application.

```python
from src.testkit import RouteRunner

@pytest.mark.asyncio
async def test_my_plugin_health():
    runner = RouteRunner()
    result = await runner.run("my_plugin.health", {"ping": True})
    assert result.status_code == 200
    assert result.body == {"status": "ok"}
```

### Signature

```
await runner.run(route_id: str, payload: dict | None = None, *, tenant: str | None = None) -> RouteRunResult
```

### RouteRunResult

| Attribute     | Type         | Description                              |
|---------------|--------------|------------------------------------------|
| `route_id`    | `str`        | Identifier of the executed route         |
| `status_code` | `int`        | HTTP status code (200 in fallback mode)  |
| `body`        | `Any`        | Response body decoded from JSON          |

---

## WorkflowRunner

Run workflows with an in-memory backend — no Temporal cluster or Postgres required.

```python
from src.testkit import WorkflowRunner, FakeWorkflowBackend

@pytest.mark.asyncio
async def test_credit_approval():
    runner = WorkflowRunner()
    result = await runner.run(
        "credit_approval",
        workflow_id="wf-42",
        input={"client_id": 42},
    )
    assert result.status == "completed"
```

### FakeWorkflowBackend

For lower-level control, use `FakeWorkflowBackend` directly:

```python
from src.testkit import FakeWorkflowBackend, WorkflowResult

backend = FakeWorkflowBackend()

# Pre-configure a specific result
handle = await backend.start_workflow(
    workflow_name="credit_approval",
    workflow_id="wf-42",
    input={"client_id": 42},
    namespace="bank-a",
    task_queue="default",
)
backend.set_result(handle, WorkflowResult(status="failed", output={"step": 3}))

result = await backend.await_completion(handle=handle)
assert result.status == "failed"
```

---

## MockCapabilityGateway

Configurable mock for `CapabilityGatewayProtocol`.

```python
from src.testkit import MockCapabilityGateway, CapabilityDeniedError

gateway = MockCapabilityGateway()
gateway.declare("my_plugin", ["db.read", "db.write"])
gateway.add_check_result("my_plugin", "db.read", allowed=True)
gateway.add_check_result("my_plugin", "db.write", allowed=False)

# Passes — allowed=True
gateway.check("my_plugin", "db.read", scope="users")

# Raises CapabilityDeniedError — allowed=False
with pytest.raises(CapabilityDeniedError):
    gateway.check("my_plugin", "db.write", scope="users")

# Inspect calls
assert gateway.check_calls == [("my_plugin", "db.read", "users")]
```

---

## Recorder / Replay

Record HTTP sessions to HAR cassettes and replay them in future test runs.

### @cassette decorator

VCR-style decorator for automatic record/replay:

```python
from src.testkit.recorder import cassette

@cassette("tests/cassettes/bki_score.yaml")
async def test_bki_returns_score(client):
    resp = await client.get("https://bki.local/api/score?id=42")
    assert resp.status_code == 200
```

Modes: `auto` (record if missing, replay if exists), `record` (always record),
`replay` (fail if cassette missing).

### HARRecorder

Manual recording:

```python
from src.testkit.recorder import HARRecorder

recorder = HARRecorder(mask_secrets=True)
async with recorder.async_client() as client:
    await client.get("https://api.example.com/v1/items")
recorder.cassette.save(Path("items.har.json"))
```

### Replay from cassette

```python
from src.testkit.recorder import load_cassette, build_replay_transport
import httpx

cassette = load_cassette("items.har.json")
transport = build_replay_transport(cassette)
async with httpx.AsyncClient(transport=transport) as client:
    resp = await client.get("https://api.example.com/v1/items")
    assert resp.status_code == 200
```

---

## Assertion Helpers

### assert_audit_event

```python
from src.testkit import assert_audit_event

events: list[dict] = []
gateway = AuthorizationGateway(
    capability_gateway=gate,
    audit_callback=events.append,
)
await gateway.authorize(principal="p1", resource="db.read", action="check")

record = assert_audit_event(events, event="authorization.decision", outcome="allow")
assert record["principal"] == "p1"
```

### assert_metric_recorded

```python
from src.testkit import assert_metric_recorded
from src.backend.infrastructure.observability.memory_metrics import MemoryMetricsBackend

metrics = MemoryMetricsBackend()
metrics.inc_counter("auth.login", labels={"tenant": "acme"})
metrics.inc_counter("auth.login", labels={"tenant": "acme"})

val = assert_metric_recorded(metrics, "auth.login", labels={"tenant": "acme"}, at_least=2.0)
assert val == 2.0
```

---

## Fixtures

The following fixtures are automatically registered via `src.testkit.pytest_plugin`:

| Fixture             | Type                          | Description                                 |
|---------------------|-------------------------------|---------------------------------------------|
| `har_recorder`      | `HARRecorder`                 | HAR recorder with mask_secrets=True         |
| `har_cassette_path` | `pathlib.Path`                | Temp path for saving cassettes             |
| `memory_metrics`    | `MemoryMetricsBackend`        | Fresh in-memory metrics backend            |
| `audit_events`      | `list[dict[str, Any]]`        | Empty list for audit_callback capture      |

---

## Migrating from `testkit`

Plugin authors who previously used the internal `testkit` package should
migrate to `src.testkit` for new tests:

| Old import                           | New import                        |
|--------------------------------------|-----------------------------------|
| `from testkit import RouteRunner`    | `from src.testkit import RouteRunner` |
| `from testkit.recorder import ...`   | `from src.testkit.recorder import ...` |
| `from testkit.replay import ...`     | `from src.testkit.recorder import ...` |

The old `testkit` package remains supported but new features will only
be added to `src.testkit`.
