"""Focused tests for ``tools/checks/contract_diff_gate`` (Wave OP-6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.checks.contract_diff_gate import (
    ContractBreakingChange,
    ContractDiff,
    _diff_graphql,
    _diff_grpc,
    _diff_rest,
    _load_json,
    diff_contracts,
    main,
)


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def contracts_dir(tmp_path: Path) -> Path:
    """Contracts directory."""
    d = tmp_path / "contracts"
    d.mkdir()
    return d


@pytest.fixture
def baseline_dir(tmp_path: Path) -> Path:
    """Baseline directory."""
    d = tmp_path / "baseline"
    d.mkdir()
    return d


class TestLoadJson:
    def test_load_existing(self, tmp_path: Path) -> None:
        f = tmp_path / "x.json"
        f.write_text('{"a": 1}', encoding="utf-8")
        assert _load_json(f) == {"a": 1}

    def test_load_missing_returns_empty(self, tmp_path: Path) -> None:
        assert _load_json(tmp_path / "missing.json") == {}

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("not json", encoding="utf-8")
        with pytest.raises(SystemExit):
            _load_json(f)


class TestRestDiff:
    """Tests для _diff_rest() — OpenAPI breaking changes."""

    def test_no_changes(self) -> None:
        spec = {
            "paths": {
                "/users": {
                    "get": {
                        "requestBody": {
                            "content": {"application/json": {"schema": {"required": []}}}
                        },
                        "responses": {
                            "200": {"content": {"application/json": {"schema": {"properties": {"id": {"type": "integer"}}}}}}
                        },
                    }
                }
            }
        }
        breaking, nb = _diff_rest(spec, spec)
        assert breaking == []
        assert nb == 1

    def test_endpoint_removed(self) -> None:
        baseline = {"paths": {"/users": {"get": {}}, "/users/{id}": {"delete": {}}}}
        current = {"paths": {"/users": {"get": {}}}}
        breaking, _ = _diff_rest(current, baseline)
        assert len(breaking) == 1
        assert breaking[0].change_type == "removed_endpoint"
        assert "DELETE" in breaking[0].location

    def test_endpoint_path_changed(self) -> None:
        baseline = {"paths": {"/v1/users": {"get": {}}}}
        current = {"paths": {"/v2/users": {"get": {}}}}
        breaking, _ = _diff_rest(current, baseline)
        assert len(breaking) == 1
        assert "GET /v1/users" in breaking[0].location

    def test_required_field_added(self) -> None:
        baseline_op = {
            "requestBody": {
                "content": {"application/json": {"schema": {"required": ["name"]}}}
            },
            "responses": {"200": {"content": {"application/json": {"schema": {}}}}},
        }
        current_op = {
            "requestBody": {
                "content": {"application/json": {"schema": {"required": ["name", "email"]}}}
            },
            "responses": {"200": {"content": {"application/json": {"schema": {}}}}},
        }
        baseline = {"paths": {"/users": {"post": baseline_op}}}
        current = {"paths": {"/users": {"post": current_op}}}
        breaking, _ = _diff_rest(current, baseline)
        assert any(c.change_type == "required_field_added" for c in breaking)
        assert any("email" in c.location for c in breaking)

    def test_response_field_removed(self) -> None:
        baseline_op = {
            "requestBody": {"content": {"application/json": {"schema": {}}}},
            "responses": {
                "200": {
                    "content": {"application/json": {"schema": {"properties": {"id": {}, "email": {}}}}}
                }
            },
        }
        current_op = {
            "requestBody": {"content": {"application/json": {"schema": {}}}},
            "responses": {
                "200": {
                    "content": {"application/json": {"schema": {"properties": {"id": {}}}}}
                }
            },
        }
        baseline = {"paths": {"/users": {"get": baseline_op}}}
        current = {"paths": {"/users": {"get": current_op}}}
        breaking, _ = _diff_rest(current, baseline)
        assert any(c.change_type == "response_field_removed" for c in breaking)
        assert any("email" in c.location for c in breaking)


class TestGraphqlDiff:
    """Tests для _diff_graphql() — GraphQL breaking changes."""

    def test_no_changes(self) -> None:
        spec = {
            "__schema": {
                "types": [
                    {"name": "User", "fields": [{"name": "id"}, {"name": "email"}]},
                    {"name": "__Schema", "fields": []},  # Introspection type.
                ]
            }
        }
        breaking, nb = _diff_graphql(spec, spec)
        assert breaking == []

    def test_type_removed(self) -> None:
        baseline = {
            "__schema": {
                "types": [
                    {"name": "User", "fields": [{"name": "id"}]},
                    {"name": "Order", "fields": [{"name": "id"}]},
                ]
            }
        }
        current = {
            "__schema": {
                "types": [
                    {"name": "User", "fields": [{"name": "id"}]},
                ]
            }
        }
        breaking, _ = _diff_graphql(current, baseline)
        assert any(c.change_type == "type_removed" for c in breaking)
        assert any("Order" in c.location for c in breaking)

    def test_field_removed(self) -> None:
        baseline = {
            "__schema": {
                "types": [
                    {"name": "User", "fields": [{"name": "id"}, {"name": "email"}]},
                ]
            }
        }
        current = {
            "__schema": {
                "types": [
                    {"name": "User", "fields": [{"name": "id"}]},
                ]
            }
        }
        breaking, _ = _diff_graphql(current, baseline)
        assert any(c.change_type == "field_removed" for c in breaking)
        assert any("User.email" in c.location for c in breaking)

    def test_introspection_types_skipped(self) -> None:
        baseline = {
            "__schema": {
                "types": [
                    {"name": "__Schema", "fields": [{"name": "types"}]},
                ]
            }
        }
        current = {"__schema": {"types": []}}
        # __Schema is introspection — should NOT be flagged.
        breaking, _ = _diff_graphql(current, baseline)
        assert breaking == []


class TestGrpcDiff:
    """Tests для _diff_grpc() — gRPC proto JSON breaking changes."""

    def test_no_changes(self) -> None:
        spec = {
            "services": [
                {"name": "UserService", "methods": [{"name": "GetUser"}]},
            ]
        }
        breaking, _ = _diff_grpc(spec, spec)
        assert breaking == []

    def test_service_removed(self) -> None:
        baseline = {
            "services": [
                {"name": "UserService", "methods": [{"name": "GetUser"}]},
                {"name": "OrderService", "methods": [{"name": "GetOrder"}]},
            ]
        }
        current = {
            "services": [
                {"name": "UserService", "methods": [{"name": "GetUser"}]},
            ]
        }
        breaking, _ = _diff_grpc(current, baseline)
        assert any(c.change_type == "service_removed" for c in breaking)
        assert any("OrderService" in c.location for c in breaking)

    def test_method_removed(self) -> None:
        baseline = {
            "services": [
                {
                    "name": "UserService",
                    "methods": [{"name": "GetUser"}, {"name": "DeleteUser"}],
                }
            ]
        }
        current = {
            "services": [
                {"name": "UserService", "methods": [{"name": "GetUser"}]},
            ]
        }
        breaking, _ = _diff_grpc(current, baseline)
        assert any(c.change_type == "method_removed" for c in breaking)
        assert any("DeleteUser" in c.location for c in breaking)


class TestContractDiffDataclass:
    """Tests для ContractDiff properties."""

    def test_total_breaking(self) -> None:
        diff = ContractDiff(
            rest_breaking=[ContractBreakingChange("rest", "x", "y", "z")],
            graphql_breaking=[
                ContractBreakingChange("graphql", "x", "y", "z"),
                ContractBreakingChange("graphql", "x", "y", "z"),
            ],
            grpc_breaking=[],
        )
        assert diff.total_breaking == 3
        assert diff.has_breaking is True

    def test_no_breaking(self) -> None:
        diff = ContractDiff()
        assert diff.total_breaking == 0
        assert diff.has_breaking is False


class TestDiffContracts:
    """End-to-end tests для diff_contracts() через directories."""

    def test_no_baseline_no_breaking(self, contracts_dir, baseline_dir) -> None:
        """Empty baseline → no breaking changes."""
        _write_json(
            contracts_dir / "rest_openapi.json",
            {"paths": {"/users": {"get": {}}}},
        )
        diff = diff_contracts(current_dir=contracts_dir, baseline_dir=baseline_dir)
        assert diff.total_breaking == 0

    def test_rest_breaking_detected(self, contracts_dir, baseline_dir) -> None:
        baseline_rest = {"paths": {"/users": {"delete": {}}}}
        current_rest = {"paths": {}}
        _write_json(baseline_dir / "rest_openapi.json", baseline_rest)
        _write_json(contracts_dir / "rest_openapi.json", current_rest)

        diff = diff_contracts(current_dir=contracts_dir, baseline_dir=baseline_dir)
        assert len(diff.rest_breaking) == 1
        assert diff.has_breaking is True


class TestCLI:
    """CLI tests через main()."""

    def test_cli_pass(self, tmp_path, capsys) -> None:
        """Same schemas → exit 0."""
        contracts_dir = tmp_path / "contracts"
        baseline_dir = tmp_path / "baseline"
        contracts_dir.mkdir()
        baseline_dir.mkdir()
        _write_json(
            contracts_dir / "rest_openapi.json",
            {"paths": {"/users": {"get": {}}}},
        )
        _write_json(
            baseline_dir / "rest_openapi.json",
            {"paths": {"/users": {"get": {}}}},
        )

        import sys
        old_argv = sys.argv
        sys.argv = [
            "contract_diff_gate",
            "diff",
            "--current",
            str(contracts_dir),
            "--baseline",
            str(baseline_dir),
        ]
        try:
            exit_code = main()
        finally:
            sys.argv = old_argv

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "RESULT: PASS" in captured.out

    def test_cli_fail_on_breaking(self, tmp_path) -> None:
        """Breaking change → exit 1."""
        contracts_dir = tmp_path / "contracts"
        baseline_dir = tmp_path / "baseline"
        contracts_dir.mkdir()
        baseline_dir.mkdir()
        _write_json(
            baseline_dir / "rest_openapi.json",
            {"paths": {"/users": {"delete": {}}}},
        )
        _write_json(
            contracts_dir / "rest_openapi.json",
            {"paths": {}},
        )

        import sys
        old_argv = sys.argv
        sys.argv = [
            "contract_diff_gate",
            "diff",
            "--current",
            str(contracts_dir),
            "--baseline",
            str(baseline_dir),
        ]
        try:
            exit_code = main()
        finally:
            sys.argv = old_argv

        assert exit_code == 1

    def test_cli_missing_current(self, tmp_path) -> None:
        """Missing current dir → exit 2."""
        import sys
        old_argv = sys.argv
        sys.argv = [
            "contract_diff_gate",
            "diff",
            "--current",
            str(tmp_path / "missing"),
            "--baseline",
            str(tmp_path / "baseline"),
        ]
        try:
            with pytest.raises(SystemExit):
                main()
        finally:
            sys.argv = old_argv

    def test_cli_first_run_no_baseline(self, tmp_path, capsys) -> None:
        """First run без baseline → WARN + exit 0."""
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()
        baseline = tmp_path / "missing_baseline"
        _write_json(
            contracts_dir / "rest_openapi.json",
            {"paths": {}},
        )

        import sys
        old_argv = sys.argv
        sys.argv = [
            "contract_diff_gate",
            "diff",
            "--current",
            str(contracts_dir),
            "--baseline",
            str(baseline),
        ]
        try:
            exit_code = main()
        finally:
            sys.argv = old_argv

        # First run = empty baseline → no violations.
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "first run" in captured.err.lower() or "baseline" in captured.err.lower()

    def test_cli_update_baseline(self, tmp_path) -> None:
        """--update-baseline copies current to baseline."""
        contracts_dir = tmp_path / "contracts"
        baseline_dir = tmp_path / "baseline"
        contracts_dir.mkdir()
        baseline_dir.mkdir()
        _write_json(
            contracts_dir / "rest_openapi.json",
            {"paths": {"/users": {"get": {}}}},
        )
        _write_json(
            baseline_dir / "rest_openapi.json",
            {"paths": {}},
        )

        import sys
        old_argv = sys.argv
        sys.argv = [
            "contract_diff_gate",
            "diff",
            "--current",
            str(contracts_dir),
            "--baseline",
            str(baseline_dir),
            "--update-baseline",
        ]
        try:
            main()
        finally:
            sys.argv = old_argv

        # Baseline should now equal current.
        baseline_rest = json.loads(
            (baseline_dir / "rest_openapi.json").read_text()
        )
        assert baseline_rest == {"paths": {"/users": {"get": {}}}}


class TestRealisticExample:
    """Realistic: full multi-protocol scenario."""

    def test_multi_protocol_breaking_changes(self, tmp_path) -> None:
        """REST + GraphQL + gRPC breaking changes detected."""
        contracts_dir = tmp_path / "contracts"
        baseline_dir = tmp_path / "baseline"
        contracts_dir.mkdir()
        baseline_dir.mkdir()
        # REST: remove endpoint.
        _write_json(
            baseline_dir / "rest_openapi.json",
            {"paths": {"/users": {"get": {}}, "/users/{id}": {"delete": {}}}},
        )
        _write_json(
            contracts_dir / "rest_openapi.json",
            {"paths": {"/users": {"get": {}}}},
        )

        # GraphQL: remove type.
        _write_json(
            baseline_dir / "graphql_introspection.json",
            {"__schema": {"types": [{"name": "User", "fields": [{"name": "id"}]}]}},
        )
        _write_json(
            contracts_dir / "graphql_introspection.json",
            {"__schema": {"types": []}},
        )

        # gRPC: remove service.
        _write_json(
            baseline_dir / "grpc_proto.json",
            {"services": [{"name": "UserService", "methods": [{"name": "GetUser"}]}]},
        )
        _write_json(
            contracts_dir / "grpc_proto.json",
            {"services": []},
        )

        diff = diff_contracts(current_dir=contracts_dir, baseline_dir=baseline_dir)

        # Each protocol detected ≥1 breaking change.
        assert len(diff.rest_breaking) >= 1
        assert len(diff.graphql_breaking) >= 1
        assert len(diff.grpc_breaking) >= 1
        assert diff.total_breaking >= 3
        assert diff.has_breaking is True
