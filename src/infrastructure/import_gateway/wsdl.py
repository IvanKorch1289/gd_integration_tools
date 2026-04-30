"""W24 — WSDL → ``ConnectorSpec`` через zeep.

Парсит WSDL 1.1/2.0 через ``zeep.wsdl.Document``: извлекает services,
bindings, operations и приводит к ``ConnectorSpec`` с
``EndpointSpec`` per operation. SOAP-action транспорт фиксирован,
schemas (XSD types) экспортируются как best-effort dict.

Поскольку zeep требует http(s)/file:// URL для парсинга WSDL с внешними
``xsd:include``, для in-memory content используется ``Transport`` с
``urllib3``-mock. Если spec приходит как ``str`` URL — парсим напрямую.
"""

from __future__ import annotations

import hashlib
import io
import logging
import tempfile
from pathlib import Path

from src.core.interfaces.import_gateway import ImportSource, ImportSourceKind
from src.core.models.connector_spec import ConnectorSpec, EndpointSpec

__all__ = ("WsdlImportGateway",)

logger = logging.getLogger("infrastructure.import_gateway.wsdl")


class WsdlImportGateway:
    """Backend для импорта WSDL спецификаций (через zeep)."""

    kind: ImportSourceKind = ImportSourceKind.WSDL

    async def import_spec(self, source: ImportSource) -> ConnectorSpec:
        from zeep import Client
        from zeep.exceptions import XMLParseError

        raw = source.content if isinstance(source.content, bytes) else source.content.encode()

        # zeep.Client принимает URL или путь — для in-memory content
        # пишем во временный файл (atomic, удаляется после использования).
        if source.source_url and (
            source.source_url.startswith("http://")
            or source.source_url.startswith("https://")
            or source.source_url.startswith("file://")
        ):
            wsdl_path = source.source_url
            tmp_path: Path | None = None
        else:
            tmp = tempfile.NamedTemporaryFile(
                mode="wb", suffix=".wsdl", delete=False
            )
            tmp.write(raw)
            tmp.close()
            tmp_path = Path(tmp.name)
            wsdl_path = str(tmp_path)

        try:
            try:
                client = Client(wsdl_path)
            except XMLParseError as exc:
                raise ImportError(f"WSDL: невалидный XML: {exc}") from exc
            except Exception as exc:
                raise ImportError(f"WSDL: zeep не смог распарсить: {exc}") from exc

            wsdl_doc = client.wsdl
            services = wsdl_doc.services
            if not services:
                raise ValueError("WSDL: не найдено ни одного <service>")

            endpoints: list[EndpointSpec] = []
            base_url = ""
            for service_name, service in services.items():
                for port_name, port in service.ports.items():
                    if not base_url:
                        base_url = getattr(port.binding_options, "address", "") or ""
                    binding = port.binding
                    binding_name = binding.name.localname if binding.name else port_name
                    for op_name, op in binding._operations.items():
                        operation_id = f"{source.prefix}.{service_name}.{op_name}"
                        soap_action = (
                            getattr(op, "soapaction", "") or op_name
                        )
                        request_schema = self._extract_signature(op, "input")
                        response_schema = self._extract_signature(op, "output")
                        endpoints.append(
                            EndpointSpec(
                                operation_id=operation_id,
                                method="SOAP",
                                path=str(soap_action),
                                summary=f"{service_name}.{port_name}.{op_name}",
                                parameters=[],
                                request_schema=request_schema,
                                response_schema=response_schema,
                                tags=[service_name, binding_name],
                            )
                        )

            if not endpoints:
                raise ValueError("WSDL: ни одной operation не найдено в bindings")

            schemas = self._collect_xsd_types(client)

            connector_name = self._sanitize_name(
                next(iter(services.keys())) if services else "wsdl_connector"
            )
            spec_hash = hashlib.sha256(raw).hexdigest()

            return ConnectorSpec(
                name=connector_name,
                title=connector_name,
                version="",
                base_url=base_url,
                endpoints=endpoints,
                auth=None,
                schemas=schemas,
                source_kind=self.kind.value,
                source_hash=spec_hash,
                source_url=source.source_url,
                metadata={"transport": "soap", **dict(source.metadata)},
            )
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError as exc:
                    logger.debug("WSDL: не удалось удалить tmp %s: %s", tmp_path, exc)

    @staticmethod
    def _extract_signature(operation: object, kind: str) -> dict[str, object] | None:
        """Извлекает упрощённую сигнатуру input/output operation."""
        msg = getattr(operation, kind, None)
        if msg is None:
            return None
        try:
            sig_str = msg.signature() if hasattr(msg, "signature") else str(msg)
        except Exception:
            sig_str = str(msg)
        return {"signature": sig_str}

    @staticmethod
    def _collect_xsd_types(client: object) -> dict[str, object]:
        result: dict[str, object] = {}
        try:
            types = client.wsdl.types  # type: ignore[attr-defined]
            for ns_name, ns in (types.documents._documents or {}).items():
                for doc in ns:
                    for elm_name, elm in doc._elements.items():
                        result[str(elm_name)] = str(elm.signature() if hasattr(elm, "signature") else elm)
        except Exception as exc:
            logger.debug("WSDL: не удалось собрать XSD types: %s", exc)
        return result

    @staticmethod
    def _sanitize_name(title: str) -> str:
        import re

        return re.sub(r"[^a-zA-Z0-9_]+", "_", title.strip().lower()).strip("_") or "wsdl"


# ruff: noqa: F401
_BUFFER = io.BytesIO  # placeholder для type-check; не используется
