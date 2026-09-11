"""Focused tests for ``core.connectors`` (Wave 1 P0 #6)."""

from __future__ import annotations

import pytest

from src.backend.core.connectors import (
    AuthModel,
    BaseConnector,
    ConnectorHealth,
    ConnectorMetadata,
    ConnectorRegistry,
    ConnectorStatus,
    OperationSchema,
    get_connector_registry,
)
from src.backend.core.connectors.registry import reset_connector_registry


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_connector_registry()


class _DummyConnector(BaseConnector):
    """Test connector."""

    def __init__(
        self,
        *,
        name: str = "dummy",
        category: str = "test",
        auth_model: AuthModel = AuthModel.NONE,
    ) -> None:
        self._name = name
        self._category = category
        self._auth_model = auth_model

    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            name=self._name,
            version="1.0.0",
            category=self._category,
            auth_model=self._auth_model,
        )

    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        }

    async def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            status=ConnectorStatus.HEALTHY,
            latency_ms=10.0,
        )

    async def test_connection(self, config: dict) -> bool:
        return "url" in config

    def operations(self) -> list[OperationSchema]:
        return [
            OperationSchema(name="get", description="HTTP GET"),
            OperationSchema(name="post", description="HTTP POST"),
        ]


class TestAuthModelEnum:
    def test_values(self) -> None:
        assert AuthModel.NONE.value == "none"
        assert AuthModel.API_KEY.value == "api_key"
        assert AuthModel.BEARER.value == "bearer"
        assert AuthModel.BASIC.value == "basic"
        assert AuthModel.OAUTH2.value == "oauth2"
        assert AuthModel.CERTIFICATE.value == "certificate"


class TestConnectorStatusEnum:
    def test_values(self) -> None:
        assert ConnectorStatus.HEALTHY.value == "healthy"
        assert ConnectorStatus.DEGRADED.value == "degraded"
        assert ConnectorStatus.UNHEALTHY.value == "unhealthy"
        assert ConnectorStatus.UNKNOWN.value == "unknown"


class TestConnectorMetadata:
    def test_init_defaults(self) -> None:
        m = ConnectorMetadata(
            name="x", version="1.0", category="http", auth_model=AuthModel.NONE
        )
        assert m.description == ""
        assert m.owner == ""
        assert m.tags == []
        assert m.documentation_url == ""

    def test_init_with_values(self) -> None:
        m = ConnectorMetadata(
            name="x",
            version="1.0",
            category="http",
            auth_model=AuthModel.API_KEY,
            description="My HTTP connector",
            owner="team-payments",
            tags=["prod", "critical"],
            documentation_url="https://docs.example.com/x",
        )
        assert m.description == "My HTTP connector"
        assert m.owner == "team-payments"
        assert m.tags == ["prod", "critical"]
        assert m.documentation_url == "https://docs.example.com/x"


class TestOperationSchema:
    def test_init_defaults(self) -> None:
        o = OperationSchema(name="get")
        assert o.description == ""
        assert o.input_schema == {}
        assert o.output_schema == {}

    def test_init_with_schemas(self) -> None:
        o = OperationSchema(
            name="post",
            description="Create",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        )
        assert o.input_schema == {"type": "object"}


class TestConnectorHealth:
    def test_init_defaults(self) -> None:
        h = ConnectorHealth(status=ConnectorStatus.HEALTHY)
        assert h.latency_ms is None
        assert h.error is None
        assert h.details == {}

    def test_init_with_error(self) -> None:
        h = ConnectorHealth(
            status=ConnectorStatus.UNHEALTHY,
            latency_ms=5000.0,
            error="timeout",
            details={"host": "api.example.com"},
        )
        assert h.error == "timeout"
        assert h.details["host"] == "api.example.com"


class TestBaseConnectorInterface:
    def test_abc_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            BaseConnector()  # type: ignore[abstract]

    def test_abstract_methods(self) -> None:
        methods = BaseConnector.__abstractmethods__
        assert "metadata" in methods
        assert "config_schema" in methods
        assert "health_check" in methods
        assert "test_connection" in methods
        assert "operations" in methods


class TestDummyConnector:
    """Test connector используется в registry tests."""

    def test_metadata(self) -> None:
        c = _DummyConnector()
        meta = c.metadata()
        assert meta.name == "dummy"
        assert meta.category == "test"
        assert meta.auth_model == AuthModel.NONE

    def test_config_schema(self) -> None:
        c = _DummyConnector()
        schema = c.config_schema()
        assert schema["type"] == "object"
        assert "url" in schema["properties"]

    async def test_health_check(self) -> None:
        c = _DummyConnector()
        h = await c.health_check()
        assert h.status == ConnectorStatus.HEALTHY
        assert h.latency_ms == 10.0

    async def test_test_connection_success(self) -> None:
        c = _DummyConnector()
        assert await c.test_connection({"url": "http://x"}) is True

    async def test_test_connection_failure(self) -> None:
        c = _DummyConnector()
        assert await c.test_connection({}) is False

    def test_operations(self) -> None:
        c = _DummyConnector()
        ops = c.operations()
        assert len(ops) == 2
        assert ops[0].name == "get"
        assert ops[1].name == "post"


class TestConnectorRegistryInit:
    def test_init_empty(self) -> None:
        r = ConnectorRegistry()
        assert r.size() == 0


class TestRegistryRegister:
    def test_register_simple(self) -> None:
        r = ConnectorRegistry()
        c = _DummyConnector(name="x")
        r.register(c)
        assert r.size() == 1

    def test_register_uses_metadata_name(self) -> None:
        r = ConnectorRegistry()
        c = _DummyConnector(name="unique-name")
        r.register(c)
        assert r.get("unique-name") is c

    def test_register_overwrites_existing(self) -> None:
        r = ConnectorRegistry()
        c1 = _DummyConnector(name="dup")
        c2 = _DummyConnector(name="dup")
        r.register(c1)
        r.register(c2)
        assert r.size() == 1
        assert r.get("dup") is c2

    def test_register_empty_name_raises(self) -> None:

        class _NoNameConnector(BaseConnector):
            def metadata(self) -> ConnectorMetadata:
                return ConnectorMetadata(
                    name="",
                    version="1.0",
                    category="x",
                    auth_model=AuthModel.NONE,
                )

            def config_schema(self) -> dict:
                return {}

            async def health_check(self) -> ConnectorHealth:
                return ConnectorHealth(status=ConnectorStatus.UNKNOWN)

            async def test_connection(self, config: dict) -> bool:
                return False

            def operations(self) -> list[OperationSchema]:
                return []

        r = ConnectorRegistry()
        with pytest.raises(ValueError, match="non-empty"):
            r.register(_NoNameConnector())


class TestRegistryUnregister:
    def test_unregister_existing(self) -> None:
        r = ConnectorRegistry()
        c = _DummyConnector(name="x")
        r.register(c)
        r.unregister("x")
        assert r.size() == 0

    def test_unregister_missing_no_op(self) -> None:
        r = ConnectorRegistry()
        r.unregister("missing")  # no error


class TestRegistryGet:
    def test_get_existing(self) -> None:
        r = ConnectorRegistry()
        c = _DummyConnector(name="x")
        r.register(c)
        assert r.get("x") is c

    def test_get_missing(self) -> None:
        r = ConnectorRegistry()
        assert r.get("missing") is None


class TestRegistryListAll:
    def test_list_all_empty(self) -> None:
        r = ConnectorRegistry()
        assert r.list_all() == []

    def test_list_all(self) -> None:
        r = ConnectorRegistry()
        r.register(_DummyConnector(name="a"))
        r.register(_DummyConnector(name="b"))
        assert r.size() == 2
        assert len(r.list_all()) == 2


class TestRegistryListMetadata:
    def test_list_metadata_no_filters(self) -> None:
        r = ConnectorRegistry()
        r.register(_DummyConnector(name="a", category="http"))
        r.register(_DummyConnector(name="b", category="messaging"))
        metas = r.list_metadata()
        assert len(metas) == 2

    def test_list_metadata_filter_category(self) -> None:
        r = ConnectorRegistry()
        r.register(_DummyConnector(name="a", category="http"))
        r.register(_DummyConnector(name="b", category="messaging"))
        result = r.list_metadata(category="http")
        assert len(result) == 1
        assert result[0].name == "a"

    def test_list_metadata_filter_auth_model(self) -> None:
        r = ConnectorRegistry()
        r.register(_DummyConnector(name="a", auth_model=AuthModel.API_KEY))
        r.register(_DummyConnector(name="b", auth_model=AuthModel.NONE))
        result = r.list_metadata(auth_model=AuthModel.API_KEY)
        assert len(result) == 1
        assert result[0].name == "a"

    def test_list_metadata_filter_tag(self) -> None:
        r = ConnectorRegistry()
        # Direct metadata with tags.
        m1 = ConnectorMetadata(
            name="a",
            version="1.0",
            category="x",
            auth_model=AuthModel.NONE,
            tags=["prod"],
        )
        m2 = ConnectorMetadata(
            name="b",
            version="1.0",
            category="x",
            auth_model=AuthModel.NONE,
            tags=["staging"],
        )

        class _C(BaseConnector):
            def metadata(self_) -> ConnectorMetadata:
                return m1 if self_._name == "a" else m2

            def config_schema(self_) -> dict:
                return {}

            async def health_check(self_) -> ConnectorHealth:
                return ConnectorHealth(status=ConnectorStatus.UNKNOWN)

            async def test_connection(self_, config: dict) -> bool:
                return False

            def operations(self_) -> list[OperationSchema]:
                return []

            def __init__(self_, name: str) -> None:
                self_._name = name

        r.register(_C(name="a"))
        r.register(_C(name="b"))
        result = r.list_metadata(tag="prod")
        assert len(result) == 1
        assert result[0].name == "a"


class TestRegistryClear:
    def test_clear(self) -> None:
        r = ConnectorRegistry()
        r.register(_DummyConnector(name="a"))
        r.register(_DummyConnector(name="b"))
        r.clear()
        assert r.size() == 0


class TestSingleton:
    def test_singleton(self) -> None:
        r1 = get_connector_registry()
        r2 = get_connector_registry()
        assert r1 is r2

    def test_reset(self) -> None:
        r1 = get_connector_registry()
        reset_connector_registry()
        r2 = get_connector_registry()
        assert r1 is not r2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import connectors

        assert len(connectors.__all__) == 8


class TestRealisticExample:
    """Real-world usage example."""

    async def test_full_lifecycle(self) -> None:
        r = get_connector_registry()
        c = _DummyConnector(name="http-api", category="http", auth_model=AuthModel.API_KEY)
        r.register(c)

        # Lookup + health check.
        found = r.get("http-api")
        assert found is c
        h = await found.health_check()
        assert h.status == ConnectorStatus.HEALTHY

        # Test connection.
        config = {"url": "https://api.example.com"}
        assert await found.test_connection(config) is True

        # List operations.
        ops = found.operations()
        assert len(ops) == 2

        # Filter for UI.
        http_connectors = r.list_metadata(category="http")
        assert len(http_connectors) == 1
