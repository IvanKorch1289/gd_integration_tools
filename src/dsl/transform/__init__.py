"""Transformations — единый фасад (C8).

Поддерживаемые engines: jmespath, jq (pyjq), bloblang (external bridge),
dataweave (lite), jinja2, xpath (lxml), xslt (lxml).

Публичный API::

    from src.dsl.transform import transform
    data = transform("user.name", payload, engine="jmespath")
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("transform",)

logger = logging.getLogger("dsl.transform")


def transform(expr: str, data: Any, *, engine: str = "jmespath") -> Any:
    """Применяет выражение к data через указанный engine."""
    engine = engine.lower()
    if engine == "jmespath":
        import jmespath

        return jmespath.search(expr, data)
    if engine == "jq":
        try:
            import pyjq  # type: ignore[import-not-found]
        except ImportError:
            raise RuntimeError("pyjq не установлен — jq недоступен")
        return pyjq.first(expr, data)
    if engine == "jinja2":
        from jinja2 import Template

        return Template(expr).render(
            **(data if isinstance(data, dict) else {"data": data})
        )
    if engine in ("xpath", "xslt"):
        from lxml import etree

        # Источник data — bytes/str/xml tree
        if isinstance(data, (bytes, bytearray, str)):
            root = etree.fromstring(
                data if isinstance(data, (bytes, bytearray)) else data.encode()
            )
        else:
            root = data
        if engine == "xpath":
            return root.xpath(expr)
        # xslt: expr — это XSLT-файл или строка
        xsl_root = etree.fromstring(expr.encode() if isinstance(expr, str) else expr)
        transform_obj = etree.XSLT(xsl_root)
        return str(transform_obj(root))
    if engine == "bloblang":
        raise RuntimeError(
            "bloblang требует external bridge (benthos/redpanda-connect CLI); "
            "реализация отложена до следующих фаз"
        )
    if engine == "dataweave":
        raise RuntimeError("dataweave-lite реализация — отложена")
    raise ValueError(f"Unknown transform engine: {engine}")
