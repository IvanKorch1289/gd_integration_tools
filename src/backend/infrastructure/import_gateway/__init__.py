"""W24 — Backends для ImportGateway.

Конкретные реализации Protocol :class:`ImportGateway`:

* :mod:`postman` — Postman Collection v2.1 → ConnectorSpec.
* :mod:`openapi` — OpenAPI 3.x (через openapi-pydantic) → ConnectorSpec.
* :mod:`wsdl` — WSDL 1.1/2.0 (через zeep) → ConnectorSpec.
* :mod:`factory` — :func:`build_import_gateway` (match по
  :class:`ImportSourceKind`) с lazy import тяжёлых backends.

Composition root: ``services/integrations/import_service.py``.
"""

from src.infrastructure.import_gateway.factory import build_import_gateway

__all__ = ("build_import_gateway",)
