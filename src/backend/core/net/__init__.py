"""Сетевые утилиты ядра.

Содержит helper'ы для HTTP/URL обработки. В будущем сюда будет добавлен
``OutboundHttpClient`` (V15) для прохождения всех ``:external``
capabilities через WAF-прокси.
"""

from src.backend.core.net.http_utils import ensure_url_protocol, generate_link_page

__all__ = ("ensure_url_protocol", "generate_link_page")
