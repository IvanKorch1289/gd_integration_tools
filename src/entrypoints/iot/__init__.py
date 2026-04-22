"""IoT-коннекторы (opt-in `gdi[iot]`) — C10.

Поддерживаемые протоколы:
* OPC-UA — через `asyncua`.
* Modbus — через `pymodbus[async]`.
* CoAP — через `aiocoap`.
* LoRaWAN — через собственный light-адаптер (stub).

Каждый подмодуль загружается лениво и выдаёт осмысленную ошибку при
отсутствии extras-пакетов.
"""

__all__ = ("is_iot_available",)


def is_iot_available() -> bool:
    try:
        import asyncua  # noqa: F401
        import pymodbus  # noqa: F401
        import aiocoap  # noqa: F401

        return True
    except ImportError:
        return False
