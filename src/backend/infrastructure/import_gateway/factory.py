"""W24 — Factory для ImportGateway-backends.

``build_import_gateway(kind)`` — single dispatch по
:class:`ImportSourceKind`. Lazy import тяжёлых зависимостей (zeep,
openapi-pydantic), чтобы dev_light не падал на старте без установленных
extras.
"""

from __future__ import annotations

from src.core.interfaces.import_gateway import ImportGateway, ImportSourceKind

__all__ = ("build_import_gateway",)


def build_import_gateway(kind: ImportSourceKind) -> ImportGateway:
    """Создаёт backend по типу источника.

    Args:
        kind: ``ImportSourceKind`` (postman/openapi/wsdl).

    Returns:
        Backend, удовлетворяющий Protocol :class:`ImportGateway`.
    """
    match kind:
        case ImportSourceKind.POSTMAN:
            from src.infrastructure.import_gateway.postman import PostmanImportGateway

            return PostmanImportGateway()
        case ImportSourceKind.OPENAPI:
            from src.infrastructure.import_gateway.openapi import OpenAPIImportGateway

            return OpenAPIImportGateway()
        case ImportSourceKind.WSDL:
            from src.infrastructure.import_gateway.wsdl import WsdlImportGateway

            return WsdlImportGateway()
        case _:
            raise ValueError(f"Неизвестный ImportSourceKind: {kind!r}")
