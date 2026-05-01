"""Wiring W26.3: ClamAV → HTTP-AV → skip+warn.

Контракт callable: ``async def scan(payload: bytes) -> AntivirusScanResult``.

* Primary — ClamAV (unix socket / TCP) через factory.
* Fallback 1 — HTTP-AV (cloud-сервис).
* Fallback 2 — ``skip+warn``: возвращает ``AntivirusScanResult(clean=True)``
  с ``backend="skip"``, метрика инкрементируется. **Compliance-риск:
  любой пропуск должен фиксироваться в audit и сопровождаться
  WARNING-логом**, чтобы оператор видел, сколько файлов прошло без
  проверки.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from src.core.interfaces.antivirus import AntivirusBackend, AntivirusScanResult

__all__ = ("AntivirusCallable", "build_antivirus_fallbacks", "build_antivirus_primary")

logger = logging.getLogger(__name__)

AntivirusCallable = Callable[[bytes], Awaitable[AntivirusScanResult]]


def _wrap_backend(backend: AntivirusBackend) -> AntivirusCallable:
    async def _scan(payload: bytes) -> AntivirusScanResult:
        return await backend.scan_bytes(payload)

    return _scan


def _build_clamav_unix() -> AntivirusCallable | None:
    try:
        from src.infrastructure.antivirus.backends.clamav_unix import ClamAVUnixBackend
    except ImportError:
        return None
    return _wrap_backend(ClamAVUnixBackend())


def _build_clamav_tcp() -> AntivirusCallable | None:
    try:
        from src.infrastructure.antivirus.backends.clamav_tcp import ClamAVTcpBackend
    except ImportError:
        return None
    return _wrap_backend(ClamAVTcpBackend())


def _build_http_av() -> AntivirusCallable:
    """HTTP-AV: всегда возвращает callable.

    Если ``AntivirusService`` не сконфигурирован, callable будет бросать
    ``ConnectionError`` при вызове — coordinator прозрачно спускается к
    следующему fallback'у в chain. Это соответствует дизайну fallback
    chain: backend всегда зарегистрирован, ошибка обрабатывается на
    runtime, а не на регистрации.
    """

    async def _http_scan(payload: bytes) -> AntivirusScanResult:
        from src.infrastructure.antivirus.backends.http import HttpAntivirusBackend
        from src.infrastructure.external_apis.antivirus import get_antivirus_service

        try:
            service = get_antivirus_service()
        except Exception as exc:  # noqa: BLE001
            raise ConnectionError(f"HTTP-AV service не сконфигурирован: {exc}") from exc
        backend = HttpAntivirusBackend(service=service)
        return await backend.scan_bytes(payload)

    return _http_scan


async def _skip_warn(payload: bytes) -> AntivirusScanResult:
    """Fallback 2: ``skip+warn`` — пропуск без проверки.

    Возвращает clean=True с явной отметкой ``backend='skip'`` для
    последующего фильтрования в audit / metrics. Обязательно WARN-лог
    с размером пропущенного payload — оператор видит, какой объём
    данных прошёл без сканирования.
    """
    logger.warning(
        "Antivirus skip+warn: scanning bypassed (payload=%d bytes). "
        "Compliance event must be recorded externally.",
        len(payload),
    )
    return AntivirusScanResult(clean=True, signature=None, backend="skip")


def build_antivirus_primary() -> AntivirusCallable | None:
    """Primary: ClamAV unix → ClamAV TCP (первый доступный).

    Возвращает ``None`` если оба ClamAV-backend'а не настроены — тогда
    coordinator переключится в ``forced`` mode и сразу пойдёт по chain.
    """
    return _build_clamav_unix() or _build_clamav_tcp()


def build_antivirus_fallbacks() -> dict[str, AntivirusCallable]:
    """Возвращает {chain_id: callable} для fallback-цепочки."""
    return {"http_av": _build_http_av(), "skip_warn": _skip_warn}
