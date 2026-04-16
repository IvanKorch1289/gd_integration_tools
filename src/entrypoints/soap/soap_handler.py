"""SOAP-сервер: приём и обработка SOAP-запросов через FastAPI.

Принимает XML/SOAP envelope через POST, парсит операцию
и payload, маршрутизирует через DSL, формирует SOAP-ответ.
"""

import logging
from typing import Any
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Request, Response

from app.core.errors import BaseError
from app.dsl.service import get_dsl_service

__all__ = ("soap_router",)

logger = logging.getLogger(__name__)

soap_router = APIRouter(prefix="/soap", tags=["SOAP"])

# Namespace-ы SOAP 1.1
_SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
_SOAP_NSMAP = {"soap": _SOAP_NS}


def _parse_soap_request(
    xml_body: bytes,
) -> tuple[str, dict[str, Any]]:
    """Парсит SOAP envelope и извлекает операцию и payload.

    Args:
        xml_body: Тело SOAP-запроса (XML bytes).

    Returns:
        Кортеж (operation_name, payload_dict).

    Raises:
        ValueError: Если XML невалиден или Body пуст.
    """
    root = ET.fromstring(xml_body)  # noqa: S314

    body = root.find(f"{{{_SOAP_NS}}}Body")
    if body is None:
        raise ValueError("SOAP Body не найден")

    # Первый дочерний элемент Body — это операция
    operation_element = next(iter(body), None)
    if operation_element is None:
        raise ValueError("SOAP Body пуст")

    # Имя операции (без namespace)
    tag = operation_element.tag
    if "}" in tag:
        operation_name = tag.split("}")[1]
    else:
        operation_name = tag

    # Собираем payload из дочерних элементов операции
    payload: dict[str, Any] = {}
    for child in operation_element:
        child_tag = child.tag
        if "}" in child_tag:
            child_tag = child_tag.split("}")[1]
        payload[child_tag] = child.text

    return operation_name, payload


def _build_soap_response(
    operation: str,
    result: Any,
) -> str:
    """Формирует SOAP response envelope.

    Args:
        operation: Имя операции.
        result: Результат обработки.

    Returns:
        XML-строка SOAP envelope.
    """
    if isinstance(result, dict):
        result_parts = "".join(
            f"<{k}>{v}</{k}>" for k, v in result.items()
        )
    else:
        result_parts = f"<result>{result}</result>"

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


def _build_soap_fault(
    fault_code: str,
    fault_string: str,
) -> str:
    """Формирует SOAP Fault envelope.

    Args:
        fault_code: Код ошибки (Client/Server).
        fault_string: Описание ошибки.

    Returns:
        XML-строка SOAP Fault.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<soap:Envelope xmlns:soap="{_SOAP_NS}">'
        "<soap:Body>"
        "<soap:Fault>"
        f"<faultcode>{fault_code}</faultcode>"
        f"<faultstring>{fault_string}</faultstring>"
        "</soap:Fault>"
        "</soap:Body>"
        "</soap:Envelope>"
    )


@soap_router.post(
    "/",
    response_class=Response,
    summary="SOAP endpoint",
    description="Принимает SOAP envelope и маршрутизирует через DSL.",
)
async def handle_soap_request(request: Request) -> Response:
    """Обработчик входящих SOAP-запросов.

    Парсит XML body, определяет операцию, диспетчеризует
    через DSL-сервис и возвращает SOAP response/fault.
    """
    content_type = "text/xml; charset=utf-8"

    try:
        xml_body = await request.body()
        operation, payload = _parse_soap_request(xml_body)

        logger.info("SOAP запрос: операция=%s", operation)

        # Маршрутизация через DSL
        dsl = get_dsl_service()
        route_id = f"soap.{operation}"

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
            return Response(
                content=xml,
                media_type=content_type,
                status_code=500,
            )

        result = (
            exchange.out_message.body
            if exchange.out_message
            else None
        )

        xml = _build_soap_response(operation, result)
        return Response(
            content=xml,
            media_type=content_type,
            status_code=200,
        )

    except ValueError as exc:
        xml = _build_soap_fault("Client", str(exc))
        return Response(
            content=xml,
            media_type=content_type,
            status_code=400,
        )
    except KeyError:
        xml = _build_soap_fault(
            "Client", "Операция не зарегистрирована в DSL"
        )
        return Response(
            content=xml,
            media_type=content_type,
            status_code=404,
        )
    except BaseError as exc:
        xml = _build_soap_fault(exc.soap_fault_code, exc.message)
        return Response(
            content=xml,
            media_type=content_type,
            status_code=exc.status_code,
        )
    except Exception as exc:
        logger.exception("SOAP ошибка: %s", exc)
        xml = _build_soap_fault("Server", str(exc))
        return Response(
            content=xml,
            media_type=content_type,
            status_code=500,
        )
