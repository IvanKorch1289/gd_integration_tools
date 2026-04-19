"""SOAP-сервер: приём и обработка SOAP-запросов через FastAPI.

Принимает XML/SOAP envelope через POST, парсит операцию
и payload, маршрутизирует через DSL или ActionHandlerRegistry,
формирует SOAP-ответ. Также предоставляет автогенерацию WSDL.
"""

import logging

import orjson
from typing import Any
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Request, Response

from app.core.errors import BaseError
from app.dsl.commands.registry import action_handler_registry
from app.dsl.service import get_dsl_service
from app.schemas.invocation import ActionCommandSchema

__all__ = ("soap_router",)

logger = logging.getLogger(__name__)

soap_router = APIRouter(prefix="/soap", tags=["SOAP"])

_SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
_WSDL_NS = "http://schemas.xmlsoap.org/wsdl/"
_XSD_NS = "http://www.w3.org/2001/XMLSchema"
_TARGET_NS = "http://gd-integration-tools/soap"


def _parse_soap_request(xml_body: bytes) -> tuple[str, dict[str, Any]]:
    """Парсит SOAP envelope и извлекает операцию и payload.

    Поддерживает два формата имён операций:
    - ``domain.method`` (например, ``orders.get``)
    - ``simple_name`` (например, ``GetOrder``)
    """
    try:
        from defusedxml.ElementTree import fromstring as safe_fromstring
        root = safe_fromstring(xml_body)
    except ImportError:
        root = ET.fromstring(xml_body)  # noqa: S314

    body = root.find(f"{{{_SOAP_NS}}}Body")
    if body is None:
        raise ValueError("SOAP Body не найден")

    operation_element = next(iter(body), None)
    if operation_element is None:
        raise ValueError("SOAP Body пуст")

    tag = operation_element.tag
    if "}" in tag:
        operation_name = tag.split("}")[1]
    else:
        operation_name = tag

    payload: dict[str, Any] = {}
    for child in operation_element:
        child_tag = child.tag.split("}")[1] if "}" in child.tag else child.tag
        payload[child_tag] = child.text

    return operation_name, payload


def _build_soap_response(operation: str, result: Any) -> str:
    """Формирует SOAP response envelope."""
    if isinstance(result, dict):
        result_parts = "".join(
            f"<{k}>{_xml_escape(v)}</{k}>" for k, v in result.items()
        )
    elif isinstance(result, list):
        result_parts = f"<result>{orjson.dumps(result).decode()}</result>"
    elif hasattr(result, "model_dump"):
        data = result.model_dump(mode="json")
        result_parts = "".join(
            f"<{k}>{_xml_escape(v)}</{k}>" for k, v in data.items()
        )
    else:
        result_parts = f"<result>{_xml_escape(result)}</result>"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<soap:Envelope xmlns:soap="{_SOAP_NS}">'
        "<soap:Body>"
        f"<{operation}Response>"
        f"{result_parts}"
        f"</{operation}Response>"
        "</soap:Body>"
        "</soap:Envelope>"
    )


def _build_soap_fault(fault_code: str, fault_string: str) -> str:
    """Формирует SOAP Fault envelope."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<soap:Envelope xmlns:soap="{_SOAP_NS}">'
        "<soap:Body>"
        "<soap:Fault>"
        f"<faultcode>{fault_code}</faultcode>"
        f"<faultstring>{_xml_escape(fault_string)}</faultstring>"
        "</soap:Fault>"
        "</soap:Body>"
        "</soap:Envelope>"
    )


def _xml_escape(value: Any) -> str:
    """Экранирует XML-спецсимволы."""
    s = str(value) if value is not None else ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


async def _dispatch_via_action(operation: str, payload: dict[str, Any]) -> Any:
    """Пытается диспетчеризовать через ActionHandlerRegistry напрямую."""
    command = ActionCommandSchema(
        action=operation,
        payload=payload,
        meta={"source": "soap"},
    )
    return await action_handler_registry.dispatch(command)


@soap_router.post(
    "/",
    response_class=Response,
    summary="SOAP endpoint",
    description="Принимает SOAP envelope и маршрутизирует через DSL или ActionHandlerRegistry.",
)
async def handle_soap_request(request: Request) -> Response:
    """Обработчик входящих SOAP-запросов.

    Стратегия маршрутизации:
    1. Если операция зарегистрирована как action → dispatch напрямую
    2. Иначе пробует DSL-маршрут (soap.{operation})
    """
    content_type = "text/xml; charset=utf-8"

    try:
        xml_body = await request.body()
        operation, payload = _parse_soap_request(xml_body)

        logger.info("SOAP запрос: операция=%s", operation)

        # Стратегия 1: прямой dispatch через ActionHandlerRegistry
        if action_handler_registry.is_registered(operation):
            result = await _dispatch_via_action(operation, payload)
            xml = _build_soap_response(operation, result)
            return Response(content=xml, media_type=content_type, status_code=200)

        # Стратегия 2: DSL-маршрут
        dsl = get_dsl_service()
        route_id = operation if "." in operation else f"soap.{operation}"

        exchange = await dsl.dispatch(
            route_id=route_id,
            body=payload,
            headers={
                "soap-action": request.headers.get("SOAPAction", ""),
                "content-type": "text/xml",
            },
        )

        if exchange.error:
            xml = _build_soap_fault("Server", exchange.error)
            return Response(content=xml, media_type=content_type, status_code=500)

        result = exchange.out_message.body if exchange.out_message else None
        xml = _build_soap_response(operation, result)
        return Response(content=xml, media_type=content_type, status_code=200)

    except ValueError as exc:
        xml = _build_soap_fault("Client", str(exc))
        return Response(content=xml, media_type=content_type, status_code=400)
    except KeyError:
        xml = _build_soap_fault("Client", "Операция не зарегистрирована")
        return Response(content=xml, media_type=content_type, status_code=404)
    except BaseError as exc:
        xml = _build_soap_fault(exc.soap_fault_code, exc.message)
        return Response(content=xml, media_type=content_type, status_code=exc.status_code)
    except Exception as exc:
        logger.exception("SOAP ошибка: %s", exc)
        xml = _build_soap_fault("Server", str(exc))
        return Response(content=xml, media_type=content_type, status_code=500)


@soap_router.get(
    "/wsdl",
    response_class=Response,
    summary="Автогенерированный WSDL",
    description="WSDL, сгенерированный из зарегистрированных actions.",
)
async def get_wsdl() -> Response:
    """Генерирует WSDL на основе зарегистрированных actions."""
    actions = action_handler_registry.list_actions()

    operations_xsd = []
    port_operations = []
    binding_operations = []

    for action in actions:
        safe_name = action.replace(".", "_")
        operations_xsd.append(
            f'    <xsd:element name="{safe_name}">'
            f'      <xsd:complexType><xsd:sequence>'
            f'        <xsd:element name="payload" type="xsd:string" minOccurs="0"/>'
            f'      </xsd:sequence></xsd:complexType>'
            f'    </xsd:element>'
            f'    <xsd:element name="{safe_name}Response">'
            f'      <xsd:complexType><xsd:sequence>'
            f'        <xsd:element name="result" type="xsd:string" minOccurs="0"/>'
            f'      </xsd:sequence></xsd:complexType>'
            f'    </xsd:element>'
        )
        port_operations.append(
            f'    <wsdl:operation name="{safe_name}">'
            f'      <wsdl:input message="tns:{safe_name}Request"/>'
            f'      <wsdl:output message="tns:{safe_name}Response"/>'
            f'    </wsdl:operation>'
        )
        binding_operations.append(
            f'    <wsdl:operation name="{safe_name}">'
            f'      <soap:operation soapAction="{action}"/>'
            f'      <wsdl:input><soap:body use="literal"/></wsdl:input>'
            f'      <wsdl:output><soap:body use="literal"/></wsdl:output>'
            f'    </wsdl:operation>'
        )

    messages = []
    for action in actions:
        safe_name = action.replace(".", "_")
        messages.append(
            f'  <wsdl:message name="{safe_name}Request">'
            f'    <wsdl:part name="parameters" element="tns:{safe_name}"/>'
            f'  </wsdl:message>'
            f'  <wsdl:message name="{safe_name}Response">'
            f'    <wsdl:part name="parameters" element="tns:{safe_name}Response"/>'
            f'  </wsdl:message>'
        )

    wsdl = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<wsdl:definitions xmlns:wsdl="{_WSDL_NS}" '
        f'xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/" '
        f'xmlns:xsd="{_XSD_NS}" '
        f'xmlns:tns="{_TARGET_NS}" '
        f'targetNamespace="{_TARGET_NS}">'
        f'  <wsdl:types><xsd:schema targetNamespace="{_TARGET_NS}">'
        + "\n".join(operations_xsd)
        + "  </xsd:schema></wsdl:types>"
        + "\n".join(messages)
        + '  <wsdl:portType name="IntegrationPortType">'
        + "\n".join(port_operations)
        + "  </wsdl:portType>"
        + '  <wsdl:binding name="IntegrationBinding" type="tns:IntegrationPortType">'
        + '    <soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>'
        + "\n".join(binding_operations)
        + "  </wsdl:binding>"
        + "</wsdl:definitions>"
    )

    return Response(content=wsdl, media_type="text/xml; charset=utf-8")
