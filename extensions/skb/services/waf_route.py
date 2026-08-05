"""Cycle-35 B2: чистая функция маршрутизации WAF для СКБ-Техно.

Раньше жила как приватный метод ``APISKBService._waf_route`` в
``src.backend.services.integrations.skb``. Решение о маршрутизации запроса
через WAF зависит только от конфигурации (env, waf_url), поэтому выделена
в чистую функцию без побочных эффектов и I/O — её удобно тестировать и
переиспользовать вне сервиса (например, из DSL-роутов справочника видов
запросов).
"""

from __future__ import annotations

__all__ = ("resolve_waf_route",)


def resolve_waf_route(
    environment: str | None, waf_url: str | None
) -> tuple[str | None, bool]:
    """Возвращает ``(waf_url, use_waf)`` для production-маршрутизации.

    Args:
        environment: Текущее окружение (``"production"`` включает WAF).
        waf_url: URL WAF из ``http_base_settings.waf_url`` (может быть ``None``).

    Returns:
        Кортеж ``(waf_url, use_waf)``: при ``environment == "production"``
        и заданном ``waf_url`` возвращается ``(waf_url, True)``, иначе
        ``(None, False)`` — запросы идут напрямую.
    """
    if environment == "production" and waf_url:
        return waf_url, True
    return None, False
