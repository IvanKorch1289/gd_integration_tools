"""Production wiring ClamAV scanner для WAF (Sprint 16 Wave 7, B-3 finale).

Фабрика для построения :class:`ClamAVPayloadScanner` из текущих
``waf_settings``. Выделена в отдельный модуль для исключения
циркулярного импорта между ``plugins.composition.waf_setup`` и
``infrastructure.antivirus.*`` через ``core.resilience``.

Используется в :func:`plugins.composition.waf_setup._build_waf_policy_from_settings`
и в Streamlit-странице мониторинга AV.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.infrastructure.logging.factory import get_logger

if TYPE_CHECKING:
    from src.backend.infrastructure.antivirus.payload_scanner import (
        ClamAVPayloadScanner,
    )

__all__ = ("build_clamav_scanner_if_enabled",)

_logger = get_logger("infrastructure.antivirus.setup")


def build_clamav_scanner_if_enabled() -> ClamAVPayloadScanner | None:
    """Возвращает :class:`ClamAVPayloadScanner` если включён feature-flag
    ``WAF_CLAMAV_ENABLED``; иначе ``None``.

    Не выполняет health-check clamd (он отложен в первый scan, см.
    :class:`ClamAVTcpBackend`). Любая ошибка инициализации логируется
    WARNING и возвращается ``None`` — startup не блокируется.
    """
    from src.backend.core.config.waf import waf_settings

    if not waf_settings.clamav_enabled:
        return None

    try:
        from src.backend.infrastructure.antivirus.backends.clamav_tcp import (
            ClamAVTcpBackend,
        )
        from src.backend.infrastructure.antivirus.payload_scanner import (
            ClamAVPayloadScanner,
        )
    except ImportError as exc:
        _logger.warning("waf.clamav.import_failed", extra={"error": repr(exc)})
        return None

    backend = ClamAVTcpBackend(
        host=waf_settings.clamav_host,
        port=waf_settings.clamav_port,
        timeout=waf_settings.clamav_timeout,
    )
    scanner = ClamAVPayloadScanner(backend, fail_open=waf_settings.clamav_fail_open)
    _logger.info(
        "waf.clamav.enabled",
        extra={
            "host": waf_settings.clamav_host,
            "port": waf_settings.clamav_port,
            "fail_open": waf_settings.clamav_fail_open,
        },
    )
    return scanner
