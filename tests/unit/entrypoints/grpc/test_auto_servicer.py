"""Unit tests for auto_servicer module."""

from __future__ import annotations

from types import ModuleType
from unittest.mock import MagicMock, patch

from src.backend.entrypoints.grpc.auto_servicer import (
    AutoServicerBundle,
    _discover_services,
    _find_add_to_server,
    _find_servicer_class,
    _import_pair,
    _verb_to_rpc_name,
    build_auto_servicers,
)


class TestDiscoverServices:
    """Tests for _discover_services."""

    def test_empty_when_dir_missing(self) -> None:
        fake_dir = MagicMock()
        fake_dir.exists.return_value = False
        with patch(
            "src.backend.entrypoints.grpc.auto_servicer._AUTO_PROTO_DIR",
            new=fake_dir,
        ):
            assert _discover_services() == []

    def test_finds_matching_pairs(self) -> None:
        fake_paths = [
            MagicMock(stem="orders_pb2", suffix=".py"),
            MagicMock(stem="orders_pb2_grpc", suffix=".py"),
            MagicMock(stem="users_pb2", suffix=".py"),
            MagicMock(stem="__init__", suffix=".py"),
        ]
        fake_dir = MagicMock()
        fake_dir.exists.return_value = True
        fake_dir.iterdir.return_value = fake_paths

        def _truediv(name):
            m = MagicMock()
            m.exists.return_value = "users" not in str(name)
            return m

        fake_dir.__truediv__ = MagicMock(side_effect=_truediv)
        with patch(
            "src.backend.entrypoints.grpc.auto_servicer._AUTO_PROTO_DIR",
            new=fake_dir,
        ):
            result = _discover_services()
        assert result == ["orders"]


class TestImportPair:
    """Tests for _import_pair."""

    def test_imports_success(self) -> None:
        fake_pb2 = ModuleType("fake_pb2")
        fake_pb2_grpc = ModuleType("fake_pb2_grpc")
        with patch("importlib.import_module", side_effect=[fake_pb2, fake_pb2_grpc]):
            result = _import_pair("orders")
        assert result is not None
        assert result[0] is fake_pb2
        assert result[1] is fake_pb2_grpc

    def test_imports_failure_returns_none(self) -> None:
        with patch("importlib.import_module", side_effect=ImportError("nope")):
            result = _import_pair("orders")
        assert result is None


class TestFindServicerClass:
    """Tests for _find_servicer_class."""

    def test_found(self) -> None:
        mod = MagicMock(spec=["OrdersAutoServiceServicer"])
        mod.OrdersAutoServiceServicer = "cls"
        assert _find_servicer_class(mod, "orders") == "cls"

    def test_missing(self) -> None:
        mod = MagicMock(spec=["Other"])
        assert _find_servicer_class(mod, "orders") is None


class TestFindAddToServer:
    """Tests for _find_add_to_server."""

    def test_found(self) -> None:
        mod = MagicMock(spec=["add_OrdersAutoServiceServicer_to_server"])
        mod.add_OrdersAutoServiceServicer_to_server = "fn"
        assert _find_add_to_server(mod, "orders") == "fn"

    def test_missing(self) -> None:
        mod = MagicMock(spec=["Other"])
        assert _find_add_to_server(mod, "orders") is None


class TestVerbToRpcName:
    """Tests for _verb_to_rpc_name."""

    def test_simple(self) -> None:
        assert _verb_to_rpc_name("orders.create") == "Create"

    def test_underscores(self) -> None:
        assert _verb_to_rpc_name("orders.get_by_id") == "GetById"

    def test_dashes(self) -> None:
        assert _verb_to_rpc_name("orders.get-by-id") == "GetById"

    def test_no_domain(self) -> None:
        assert _verb_to_rpc_name("create") == "Create"


class TestAutoServicerBundle:
    """Tests for AutoServicerBundle."""

    def test_attributes(self) -> None:
        bundle = AutoServicerBundle(
            service="orders",
            pb2=MagicMock(),
            pb2_grpc=MagicMock(),
            servicer_cls=str,
            add_to_server=print,
        )
        assert bundle.service == "orders"
        assert bundle.servicer_cls is str


class TestBuildAutoServicers:
    """Tests for build_auto_servicers."""

    def test_empty_when_no_services(self) -> None:
        with patch(
            "src.backend.entrypoints.grpc.auto_servicer._discover_services",
            return_value=[],
        ):
            assert build_auto_servicers() == ()

    def test_builds_when_all_present(self) -> None:
        fake_pb2 = MagicMock()
        fake_pb2.EmptyResponse = "EmptyResponse"
        fake_pb2_grpc = MagicMock()
        fake_pb2_grpc.OrdersAutoServiceServicer = type("Base", (), {})
        fake_pb2_grpc.add_OrdersAutoServiceServicer_to_server = MagicMock()

        fake_meta = MagicMock()
        fake_meta.action = "orders.create"
        fake_meta.output_model = None

        mock_registry = MagicMock()
        mock_registry.list_metadata.return_value = [fake_meta]

        with patch(
            "src.backend.entrypoints.grpc.auto_servicer._discover_services",
            return_value=["orders"],
        ):
            with patch(
                "src.backend.entrypoints.grpc.auto_servicer._import_pair",
                return_value=(fake_pb2, fake_pb2_grpc),
            ):
                with patch(
                    "src.backend.dsl.commands.action_registry.action_handler_registry",
                    mock_registry,
                ):
                    bundles = build_auto_servicers()
        assert len(bundles) == 1
        assert bundles[0].service == "orders"
