"""Wave 1.3 (Roadmap V10) — unit-тесты ``tools/codegen_proto.py`` CLI.

Покрывает:

* ``_group_by_service`` — правильную группировку по resource;
* ``_verb_to_rpc_name`` — CamelCase из verb;
* ``_build_proto_file_for_group`` — корректное построение ProtoFile;
* dry-run путь ``run_codegen`` с inj регистром.
"""

# ruff: noqa: S101

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest
from pydantic import BaseModel

# Импортируем модуль через importlib, чтобы избежать конфликта с file-based "tools" пакетом.
codegen = importlib.import_module("tools.codegen_proto")


class _ListReq(BaseModel):
    limit: int = 10


class _ListResp(BaseModel):
    items: list[str] = []


class _CreateReq(BaseModel):
    name: str


class _CreateResp(BaseModel):
    id: int


def _make_meta(action: str, *, side_effect: str = "read", input_model=None, output_model=None):
    """Создать ActionMetadata-stub без обращения к реестру."""
    from src.backend.core.interfaces.action_dispatcher import ActionMetadata

    return ActionMetadata(
        action=action,
        side_effect=side_effect,
        input_model=input_model,
        output_model=output_model,
        transports=("http", "grpc", "graphql"),
    )


class TestGroupByService:
    def test_groups_by_first_part(self):
        metas = [
            _make_meta("orders.list"),
            _make_meta("orders.create"),
            _make_meta("users.get"),
        ]
        groups = codegen._group_by_service(metas)
        assert {g.service for g in groups} == {"orders", "users"}
        orders_group = next(g for g in groups if g.service == "orders")
        assert {m.action for m in orders_group.actions} == {"orders.list", "orders.create"}

    def test_action_without_dot_goes_to_misc(self):
        metas = [_make_meta("standalone")]
        groups = codegen._group_by_service(metas)
        assert len(groups) == 1
        assert groups[0].service == "misc"


class TestVerbToRpcName:
    @pytest.mark.parametrize(
        ("action_id", "expected"),
        [
            ("orders.list", "List"),
            ("orders.create_many", "CreateMany"),
            ("users.get", "Get"),
            ("standalone", "Standalone"),
            ("orders.send-data", "SendData"),
        ],
    )
    def test_verb_to_rpc_name(self, action_id, expected):
        assert codegen._verb_to_rpc_name(action_id) == expected


class TestBuildProtoFileForGroup:
    def test_minimal_group_with_models(self):
        from src.backend.core.actions.proto_adapter import ProtoFile

        group = codegen._ServiceGroup(
            service="orders",
            actions=[
                _make_meta(
                    "orders.list", input_model=_ListReq, output_model=_ListResp
                ),
                _make_meta(
                    "orders.create", input_model=_CreateReq, output_model=_CreateResp
                ),
            ],
        )
        result = codegen._build_proto_file_for_group(group)
        proto = result.proto
        assert isinstance(proto, ProtoFile)
        assert proto.package == "orders.auto"
        # message-классы по обеим моделям + nested-нет.
        msg_names = {m.name for m in proto.messages}
        assert {"_ListReq", "_ListResp", "_CreateReq", "_CreateResp"} <= msg_names

        assert len(proto.services) == 1
        service = proto.services[0]
        assert service.name == "OrdersAutoService"
        rpc_names = {rpc.name for rpc in service.rpcs}
        assert rpc_names == {"List", "Create"}

    def test_action_without_models_skipped(self):
        group = codegen._ServiceGroup(
            service="empty", actions=[_make_meta("empty.action")]
        )
        result = codegen._build_proto_file_for_group(group)
        assert "ни input_model" in result.skipped[0]
        assert not result.proto.services or not result.proto.services[0].rpcs

    def test_action_with_only_input_uses_empty_response(self):
        group = codegen._ServiceGroup(
            service="orders",
            actions=[_make_meta("orders.fire", input_model=_CreateReq)],
        )
        result = codegen._build_proto_file_for_group(group)
        proto = result.proto
        msg_names = {m.name for m in proto.messages}
        assert "EmptyResponse" in msg_names
        rpc = proto.services[0].rpcs[0]
        assert rpc.response_message == "EmptyResponse"


class TestRunCodegenDryRun:
    def test_dry_run_no_writes(self, capsys):
        metas = (
            _make_meta("orders.list", input_model=_ListReq, output_model=_ListResp),
        )

        with patch.object(codegen, "_bootstrap_registry"), patch.object(
            codegen, "_filter_grpc_actions", return_value=metas
        ):
            written = codegen.run_codegen(dry_run=True)

        assert written == 0
        out = capsys.readouterr().out
        assert "найдено 1 grpc-actions" in out
        assert "orders.list" in out

    def test_no_grpc_actions(self, capsys):
        with patch.object(codegen, "_bootstrap_registry"), patch.object(
            codegen, "_filter_grpc_actions", return_value=()
        ):
            written = codegen.run_codegen(dry_run=False)
        assert written == 0
        out = capsys.readouterr().out
        assert "нет actions" in out
