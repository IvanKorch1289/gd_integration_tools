"""Cycle 12 swarm: default HTTP/network timeouts for sink operations.

Centralizes hardcoded numeric defaults previously scattered across
8 sink modules. Per D421 (constants module for timeouts), this
file is the single source of truth for default network timeouts in
sinks. Adopting sinks import from here; per-sink field still allows
explicit override (preserves existing public API).
"""
from __future__ import annotations

# Per-sink defaults. Documented here so changes propagate uniformly.
DEFAULT_SINK_TIMEOUT_S: float = 10.0
"""Default timeout for synchronous HTTP/WS/gRPC/MQTT/NATS/WebHook sinks.
Documented at S3 W1 K3 (Sink symmetry)."""

SOAP_SINK_TIMEOUT_S: float = 30.0
"""SOAP/WSDL default is longer (WSDL fetch + envelope processing)."""

SMS_SINK_TIMEOUT_S: float = 10.0
"""SMS provider HTTP health-probe timeout (separate from send timeout)."""

__all__ = (
    "DEFAULT_SINK_TIMEOUT_S",
    "SMS_SINK_TIMEOUT_S",
    "SOAP_SINK_TIMEOUT_S",
)
