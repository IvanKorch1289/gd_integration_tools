"""Wave F.8 — тесты на ActionSpec.tier + auto-inference action_id.

Покрывает:

* Default tier=2 не меняет существующее поведение (action_id остаётся None).
* tier=1 + action_id=None → инференция по path/method.
* Явный action_id всегда побеждает инференцию.
* tier=3 не инферрит (manual).
"""

# ruff: noqa: S101

from __future__ import annotations

from src.entrypoints.api.generator.specs import ActionSpec, _infer_tier1_action_id


def _stub_service():
    return None


def _spec(method: str, path: str, **kwargs) -> ActionSpec:
    return ActionSpec(
        name="dummy",
        method=method,
        path=path,
        summary="dummy",
        service_getter=_stub_service,
        service_method="get",
        **kwargs,
    )


class TestInferTier1ActionId:
    def test_get_all_path_returns_resource_list(self) -> None:
        assert _infer_tier1_action_id("/api/v1/orders/all/", "GET") == "orders.list"

    def test_get_by_id_returns_resource_get(self) -> None:
        assert (
            _infer_tier1_action_id("/api/v1/orders/id/{object_id}", "GET")
            == "orders.get"
        )

    def test_post_create_returns_resource_create(self) -> None:
        assert _infer_tier1_action_id("/api/v1/orders/create/", "POST") == "orders.create"

    def test_post_create_many(self) -> None:
        assert (
            _infer_tier1_action_id("/api/v1/orders/create_many/", "POST")
            == "orders.create_many"
        )

    def test_put_update(self) -> None:
        assert (
            _infer_tier1_action_id("/api/v1/orders/update/{object_id}", "PUT")
            == "orders.update"
        )

    def test_delete(self) -> None:
        assert (
            _infer_tier1_action_id("/api/v1/orders/delete/{object_id}", "DELETE")
            == "orders.delete"
        )


class TestActionSpecPostInit:
    def test_default_tier_is_2_no_inference(self) -> None:
        spec = _spec("GET", "/api/v1/orders/all/")
        assert spec.tier == 2
        assert spec.action_id is None

    def test_tier1_infers_action_id(self) -> None:
        spec = _spec("GET", "/api/v1/orders/all/", tier=1)
        assert spec.action_id == "orders.list"

    def test_explicit_action_id_wins_over_inference(self) -> None:
        spec = _spec(
            "GET",
            "/api/v1/orders/all/",
            tier=1,
            action_id="orders.fancy_list",
        )
        assert spec.action_id == "orders.fancy_list"

    def test_tier3_does_not_infer(self) -> None:
        spec = _spec("GET", "/api/v1/orders/all/", tier=3)
        assert spec.action_id is None
