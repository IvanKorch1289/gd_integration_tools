"""Network-isolation для markitdown-engine (V15 R-V15-5).

По умолчанию markitdown инициализируется с урезанным сетевым стеком —
:func:`markitdown_network_disabled` подменяет ``urllib.request.urlopen``
no-op'ом на время вызова. Это закрывает имплицитные resolve URL внутри
HTML/RSS-документов.

При ``network_mode='waf'`` (settings) предполагается, что вызовы
оборачиваются через :class:`OutboundHttpClient` (capability
``net.outbound.<host>:external``) — но эту ветку оставляем заглушкой
для будущего ADR. Default-OFF, согласно §10 плана.
"""

from __future__ import annotations

import contextlib
import logging
import urllib.request
from collections.abc import Iterator

__all__ = ("markitdown_network_disabled",)

logger = logging.getLogger(__name__)


class _NetworkDeniedError(RuntimeError):
    """markitdown попытался сделать outbound-запрос с network_mode='off'."""


def _denied_urlopen(*args, **kwargs):
    raise _NetworkDeniedError(
        "markitdown network access is disabled (settings.MARKITDOWN_NETWORK_MODE='off')"
    )


@contextlib.contextmanager
def markitdown_network_disabled() -> Iterator[None]:
    """Контекст: блокирует ``urllib.request.urlopen`` на время вызова.

    markitdown иногда вызывает ``urllib.request`` для resolve относительных
    ссылок внутри HTML/RSS. С network_mode='off' эти вызовы должны быть
    silent-skip; markitdown ловит исключения internally и продолжает.
    """
    original = urllib.request.urlopen
    urllib.request.urlopen = _denied_urlopen
    try:
        yield
    finally:
        urllib.request.urlopen = original
