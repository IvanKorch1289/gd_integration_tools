"""Recorder / replay public API re-exported from testkit (K5 S19 W3, S-L10-1).

This module re-exports the HAR-based HTTP recorder and VCR-style
cassette functionality from :mod:`testkit.recorder` and :mod:`testkit.replay`
for convenient access via ``src.testkit.recorder``.

See the original modules for full documentation:

* :mod:`testkit.recorder` — HAR-Recorder for recording HTTP sessions.
* :mod:`testkit.replay` — HAR-based replay via httpx.MockTransport.
* :mod:`testkit.recorder.cassette` — VCR-style ``@cassette`` decorator.
"""

from __future__ import annotations

# Re-export everything from the existing testkit implementation so that
# plugin authors can use ``from src.testkit.recorder import HARRecorder``
# without needing to know about the internal testkit package structure.

# HAR core types
from testkit.recorder import (
    HARCassette,
    HAREntry,
    HARRecorder,
    record_session,
)
from testkit.recorder.cassette import (
    CassetteMode,
    cassette,
    load_cassette as _load_cassette,
    save_cassette,
)
from testkit.recorder.secrets_mask import (
    MASKED_VALUE,
    SECRET_BODY_KEYS,
    SECRET_HEADER_KEYS,
    mask_request_body,
    mask_response_headers,
)
from testkit.replay import (
    MissingCassetteEntry,
    build_replay_transport,
    load_cassette,
)

__all__ = (
    # Core HAR types
    "HARCassette",
    "HAREntry",
    "HARRecorder",
    "record_session",
    # Cassette utilities
    "CassetteMode",
    "cassette",
    "load_cassette",
    "save_cassette",
    # Replay
    "MissingCassetteEntry",
    "build_replay_transport",
    # Secrets masking
    "MASKED_VALUE",
    "SECRET_BODY_KEYS",
    "SECRET_HEADER_KEYS",
    "mask_request_body",
    "mask_response_headers",
)
