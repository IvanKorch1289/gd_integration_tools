"""JsonFacade (S171 M27+, D292).

Pattern (D292, Ponytail): unified JSON facade wrapping orjson.
Replaces direct json.dumps/loads in hot paths.
"""
# ruff: noqa: E501
from __future__ import annotations

import json
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("core.utils.json_facade")

__all__ = ("dumps", "loads")


try:
    import orjson

    def dumps(obj: Any, **kwargs: Any) -> bytes:
        """Serialize obj to JSON bytes via orjson (3-5x faster than stdlib)."""
        return orjson.dumps(obj, **kwargs)

    def loads(data: bytes | str) -> Any:
        """Deserialize JSON via orjson."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        return orjson.loads(data)

except ImportError:

    def dumps(obj: Any, **kwargs: Any) -> str:
        """Fallback to stdlib json (slow path)."""
        _logger.warning("json_facade.orjson_missing using_stdlib")
        return json.dumps(obj, **kwargs)

    def loads(data: bytes | str) -> Any:
        return json.loads(data)
