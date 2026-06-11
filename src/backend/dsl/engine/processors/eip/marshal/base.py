from __future__ import annotations
"""S63 W3 — base.py part of marshal decomp.

DataFormat base class (4 methods).
"""

import csv
import io
import json
import pickle
import threading
import xml.etree.ElementTree as ET  # safe: used only for marshal (we generate XML)
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind

# Security: defusedxml guards against XXE / billion-laughs in XML unmarshal.
# ``pickle`` and ``xml.etree.ElementTree`` are stdlib defaults but unsafe for
# untrusted input — we import defusedxml lazily and use it for the public
# surface; stdlib ET is only used for the controlled marshal path (we generate
# the tree ourselves from a dict, never parse untrusted XML).
try:
    import defusedxml.ElementTree as DET  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — dev-light fallback
    DET = None  # type: ignore[assignment]
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

_log = get_logger(__name__)

# ── DataFormat abstract + concrete impls ─────────────────────────────

class DataFormat(ABC):
    """Abstract data format — encode (marshal) / decode (unmarshal)."""

    @property
    @abstractmethod
    def content_type(self) -> str:
        """MIME-тип: ``application/json``, ``text/xml`` и т.п."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier: ``json``, ``xml``, ``csv``, ``msgpack``, ``pickle``."""
        ...

    @abstractmethod
    def marshal(self, body: Any) -> bytes:
        """Encode in-memory object → bytes."""
        ...

    @abstractmethod
    def unmarshal(self, data: bytes, target_type: type | None = None) -> Any:
        """Decode bytes → in-memory object (target_type hint)."""
        ...

