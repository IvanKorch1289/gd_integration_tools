"""W28 — Round-trip тесты для enrichment + business процессоров.

Покрывает primitive-args batch (12 процессоров):

* enrichment.py: geoip / jwt_sign / jwt_verify / compress / decompress /
  webhook_sign / deadline.
* business.py: tenant_scope / cost_tracker / outbox / mask /
  compliance_labels.

HumanApprovalProcessor пропущен из W28: ``approval_store`` (Any-объект)
и ``notifier`` (callable) не сериализуются. OutboxProcessor возвращает
``None`` при наличии custom ``outbox_writer``.

Внимание: ``jwt_sign`` / ``jwt_verify`` / ``webhook_sign`` сериализуют
literal-секреты в YAML — для production secret-store используйте
SecretRef-маркеры (см. ``docs/reference/dsl/to_spec_audit.md``).
"""

# ruff: noqa: S101, S106

from __future__ import annotations

import pytest
import yaml

from src.dsl.builder import RouteBuilder
from src.dsl.yaml_loader import load_pipeline_from_yaml


def _round_trip(builder: RouteBuilder) -> tuple[dict, dict]:
    pipeline = builder.build()
    dump = pipeline.to_dict()
    yaml_str = yaml.safe_dump(dump, sort_keys=False, allow_unicode=True)
    rebuilt = load_pipeline_from_yaml(yaml_str)
    return dump, rebuilt.to_dict()


@pytest.mark.parametrize(
    "method,kwargs",
    [
        # ── enrichment ──
        ("geoip", {}),
        ("geoip", {"ip_field": "remote_addr"}),
        ("geoip", {"ip_header": "x-forwarded-for"}),
        (
            "geoip",
            {
                "ip_field": "addr",
                "ip_header": "x-real-ip",
                "output_property": "geo_data",
            },
        ),
        ("jwt_sign", {"secret_key": "S"}),
        (
            "jwt_sign",
            {
                "secret_key": "S",
                "algorithm": "RS256",
                "expires_in_seconds": 7200,
                "output_property": "token",
            },
        ),
        ("jwt_verify", {"secret_key": "S"}),
        (
            "jwt_verify",
            {
                "secret_key": "S",
                "algorithm": "HS512",
                "header": "X-Auth",
                "output_property": "claims",
            },
        ),
        ("compress", {}),
        ("compress", {"algorithm": "brotli", "level": 11}),
        ("decompress", {}),
        ("decompress", {"algorithm": "zstd"}),
        ("webhook_sign", {"secret": "K"}),
        ("webhook_sign", {"secret": "K", "header": "X-Sig", "algorithm": "sha512"}),
        ("deadline", {}),
        ("deadline", {"timeout_seconds": 60.0}),
        ("deadline", {"timeout_seconds": 5.0, "fail_on_exceed": False}),
        # ── business ──
        ("tenant_scope", {}),
        ("tenant_scope", {"header": "x-tid"}),
        (
            "tenant_scope",
            {"header": "x-tid", "body_path": "tenant.id", "required": False},
        ),
        ("cost_tracker", {}),
        ("outbox", {"topic": "kafka:orders.events"}),
        ("outbox", {"topic": "rabbit:notifications"}),
        ("mask", {}),
        ("mask", {"patterns": ["email", "phone"]}),
        ("mask", {"patterns": ["card"], "replacement": "[REDACTED]"}),
        ("compliance_labels", {"labels": ["PII"]}),
        ("compliance_labels", {"labels": ["PCI", "FIN", "GDPR"]}),
    ],
)
def test_w28_processor_round_trip(method: str, kwargs: dict) -> None:
    """Single-processor round-trip: builder → YAML → builder."""
    builder = RouteBuilder.from_(f"rt.w28.{method}", source="test:rt.w28")
    getattr(builder, method)(**kwargs)
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt, (
        f"Round-trip mismatch for {method}({kwargs}): {original} != {rebuilt}"
    )


def test_w28_pipeline_full_chain() -> None:
    """Реалистичный banking-pipeline: tenant → masking → outbox → compliance.

    Покрывает business-домен end-to-end с подписью и сжатием.
    """
    builder = (
        RouteBuilder.from_("rt.w28.full", source="test:rt.w28.full", description="full")
        .tenant_scope(header="x-tenant-id", required=True)
        .geoip(ip_field="client_ip")
        .compliance_labels(labels=["PII", "FIN"])
        .mask(patterns=["card", "email"])
        .compress(algorithm="gzip", level=6)
        .webhook_sign(secret="HMAC_KEY", algorithm="sha256")
        .outbox(topic="kafka:audit.events")
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    methods = [next(iter(p)) for p in original["processors"]]
    assert methods == [
        "tenant_scope",
        "geoip",
        "compliance_labels",
        "mask",
        "compress",
        "webhook_sign",
        "outbox",
    ]


def test_outbox_with_custom_writer_skipped_in_spec() -> None:
    """OutboxProcessor с custom outbox_writer — to_spec → None (skipped)."""
    from src.dsl.engine.processors.business import OutboxProcessor

    async def _custom_writer(*, topic, payload, headers):  # noqa: ANN001, ARG001
        return None

    proc = OutboxProcessor(topic="test.topic", outbox_writer=_custom_writer)
    assert proc.to_spec() is None


def test_mask_default_patterns_omitted() -> None:
    """``mask()`` без patterns → пустой spec (default набор не пишется)."""
    builder = RouteBuilder.from_("rt.mask.def", source="test:rt").mask()
    spec = builder.build().to_dict()
    assert spec["processors"][0] == {"mask": {}}


def test_compliance_labels_emits_full_list() -> None:
    """``compliance_labels`` всегда сохраняет labels (нет default-значения)."""
    builder = RouteBuilder.from_("rt.cl", source="test:rt").compliance_labels(
        labels=["PII", "PCI"]
    )
    spec = builder.build().to_dict()
    assert spec["processors"][0] == {"compliance_labels": {"labels": ["PII", "PCI"]}}


def test_jwt_sign_emits_secret_literal() -> None:
    """``jwt_sign`` сериализует secret_key как literal — задокументировано."""
    builder = RouteBuilder.from_("rt.jwt", source="test:rt").jwt_sign(secret_key="X")
    spec = builder.build().to_dict()
    assert spec["processors"][0] == {"jwt_sign": {"secret_key": "X"}}
