"""Пакет testkit.recorder — HAR-кассеты для записи HTTP-трейсов в тестах.

Публичный API:
    * :class:`HARCassette`, :class:`HAREntry`, :class:`HARRecorder` —
      запись/чтение HAR.
    * :func:`record_session` — shortcut-контекст.
    * :func:`mask_response_headers`, :func:`mask_request_body` —
      утилиты маскирования секретов (используются автоматически
      рекордером, см. :mod:`testkit.recorder.secrets_mask`).
"""

from __future__ import annotations

from testkit.recorder._har import (
    HARCassette,
    HAREntry,
    HARRecorder,
    record_session,
)
from testkit.recorder.cassette import (
    CassetteMode,
    cassette,
    load_cassette,
    save_cassette,
)
from testkit.recorder.secrets_mask import (
    MASKED_VALUE,
    SECRET_BODY_KEYS,
    SECRET_HEADER_KEYS,
    mask_request_body,
    mask_response_headers,
)

__all__ = (
    "CassetteMode",
    "HARCassette",
    "HAREntry",
    "HARRecorder",
    "MASKED_VALUE",
    "SECRET_BODY_KEYS",
    "SECRET_HEADER_KEYS",
    "cassette",
    "load_cassette",
    "mask_request_body",
    "mask_response_headers",
    "record_session",
    "save_cassette",
)
