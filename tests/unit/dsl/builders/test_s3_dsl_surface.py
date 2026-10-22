"""YAML-доступность S3-шагов (cycle 271, audit HIGH-02).

S175 #5 удалил методы ``RouteBuilder.to_s3``/... полагаясь на прямое
использование процессоров. Но ``dsl/yaml_loader/build.py`` резолвит YAML-шаг
через ``getattr(builder, proc_name)`` — без этих методов пять процессоров
существовали, имели тесты и были **недостижимы из YAML**. Объектным хранилищем
нельзя было управлять декларативно вообще.

Эти тесты фиксируют восстановленный DSL-контракт:

* четыре шага используют исходные ``@processor`` op_name;
* шаг чтения называется ``s3_get``, потому что ``from_s3`` уже занят
  ``SourcesEIPsMixin`` — это S3 poll-сенсор (другая семантика).
"""

from __future__ import annotations

import pytest

from src.backend.dsl.builders import RouteBuilder


def _builder() -> RouteBuilder:
    return RouteBuilder.from_("s3_yaml_probe", source="timer:1s")


@pytest.mark.parametrize(
    "method",
    ["to_s3", "s3_presign", "s3_delete", "s3_list"],
)
def test_s3_step_methods_exist(method: str) -> None:
    """Методы, соответствующие op_name процессоров, доступны на builder'е."""
    assert hasattr(_builder(), method), f"RouteBuilder.{method} отсутствует"


def test_s3_get_replaces_colliding_from_s3() -> None:
    """Чтение объекта экспонируется как ``s3_get``, не затирая poll-сенсор."""
    b = _builder()
    assert hasattr(b, "s3_get")
    # from_s3 обязан остаться сенсором — иначе меняется смысл существующего ключа.
    assert b.from_s3.__qualname__.startswith("SourcesEIPsMixin")


def test_from_s3_still_resolves_to_the_eip_sensor() -> None:
    """Явная защита от молчаливой смены семантики существующего YAML-ключа."""
    assert "SourcesEIPsMixin" in _builder().from_s3.__qualname__


def test_steps_compose_into_one_pipeline() -> None:
    """Несколько однотипных/разных S3-операций собираются в один pipeline."""
    b = _builder().to_s3(key_from="doc_key").s3_get(key_from="s3_key").s3_list()
    route = b.build()

    assert len(route.processors) == 3


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("to_s3", {"key_from": "k", "data_property": "body"}),
        ("s3_get", {"key_from": "s3_key", "result_property": "body"}),
        ("s3_presign", {"key_from": "s3_key", "expires_in": 600}),
        ("s3_delete", {"key_from": "s3_key"}),
        ("s3_list", {"prefix_from": "p", "result_property": "keys"}),
    ],
)
def test_step_accepts_its_documented_kwargs(
    method: str, kwargs: dict[str, object]
) -> None:
    """YAML-loader передаёт params как **kwargs — сигнатуры должны совпадать."""
    b = _builder()
    getattr(b, method)(**kwargs)  # TypeError означает рассинхрон с процессором
    assert len(b.build().processors) == 1


def test_s3_presign_rejects_non_positive_expiry() -> None:
    """Валидация процессора не должна теряться при вызове через builder."""
    with pytest.raises(ValueError):
        _builder().s3_presign(expires_in=0)


def test_yaml_route_builds_full_s3_pipeline() -> None:
    """End-to-end: YAML-loader принимает все пять S3-шагов.

    Это и есть проверка HIGH-02: до фикса ``_build_pipeline`` падал на
    ``Unknown or forbidden processor``, потому что методов на builder'е не было.
    """
    import yaml

    from src.backend.dsl.yaml_loader.build import _build_pipeline

    spec = yaml.safe_load(
        """
route_id: s3_yaml_probe
source: "timer:1s"
steps:
  - to_s3: {key_from: "doc_key", data_property: "body"}
  - s3_list: {prefix_from: "uploads/"}
  - s3_get: {key_from: "s3_key", result_property: "file_body"}
  - s3_presign: {key_from: "s3_key", expires_in: 900}
  - s3_delete: {key_from: "s3_key"}
"""
    )
    pipeline = _build_pipeline(spec)

    assert [type(p).__name__ for p in pipeline.processors] == [
        "ToS3Processor",
        "S3ListProcessor",
        "FromS3Processor",
        "S3PresignProcessor",
        "S3DeleteProcessor",
    ]
