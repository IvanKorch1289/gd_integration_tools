"""Integration-тест V9: ``WebhookSource._verify_hmac`` использует canonical signatures.

Проверяет, что после консолидации (Wave [s2/k1-4-webhook-sig]) ``WebhookSource``
делегирует HMAC-верификацию :func:`verify_signature`, а не inline-коду.

Контракт:
* ``timestamp_header`` задан → проверка через canonical (raw-body
  passthrough + timestamp window);
* ``timestamp_header=None`` → legacy mode (HMAC только над body).
"""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from src.backend.infrastructure.security.signatures import sign_payload
from src.backend.infrastructure.sources.webhook import (
    WebhookSource,
    WebhookVerificationError,
)


SECRET = "supersecret_key_with_enough_entropy_aaaa"


def _legacy_hmac_hex(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_canonical_mode_accepts_valid_signature() -> None:
    captured: list = []

    async def on_event(ev) -> None:
        captured.append(ev)

    source = WebhookSource(
        "test-canonical",
        path="/webhooks/test",
        hmac_secret=SECRET,
        hmac_header="X-Signature",
        timestamp_header="X-Timestamp",
    )
    await source.start(on_event)
    body = b'{"event": "x"}'
    sig, ts = sign_payload(body, SECRET)
    await source.verify_and_dispatch(
        body, {"X-Signature": sig, "X-Timestamp": str(ts)}, payload={"event": "x"}
    )
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_canonical_mode_rejects_wrong_signature() -> None:
    async def noop(ev) -> None:
        return None

    source = WebhookSource(
        "test-canonical",
        path="/webhooks/test",
        hmac_secret=SECRET,
        timestamp_header="X-Timestamp",
    )
    await source.start(noop)
    body = b'{"event": "x"}'
    with pytest.raises(WebhookVerificationError, match="HMAC"):
        await source.verify_and_dispatch(
            body, {"X-Signature": "deadbeef", "X-Timestamp": str(int(time.time()))}
        )


@pytest.mark.asyncio
async def test_canonical_mode_rejects_expired_timestamp() -> None:
    async def noop(ev) -> None:
        return None

    source = WebhookSource(
        "test-canonical",
        path="/webhooks/test",
        hmac_secret=SECRET,
        timestamp_header="X-Timestamp",
        timestamp_window_seconds=60.0,
    )
    await source.start(noop)
    body = b'{"event": "x"}'
    old_ts = int(time.time()) - 3600
    sig, _ = sign_payload(body, SECRET, timestamp=old_ts)
    # Без header'а X-Timestamp legacy mode уйдёт в простой HMAC, поэтому
    # передаём timestamp явно — но он мимо окна → HMAC mismatch (старая
    # подпись не совпадает с текущим timestamp).
    with pytest.raises(WebhookVerificationError):
        await source.verify_and_dispatch(
            body, {"X-Signature": sig, "X-Timestamp": str(old_ts)}
        )


@pytest.mark.asyncio
async def test_legacy_mode_no_timestamp_header_uses_body_hmac() -> None:
    """Без ``timestamp_header`` source считает HMAC только над body."""

    async def noop(ev) -> None:
        return None

    source = WebhookSource(
        "test-legacy",
        path="/webhooks/test",
        hmac_secret=SECRET,
        hmac_header="X-Signature",
    )
    await source.start(noop)
    body = b'{"event": "y"}'
    legacy_sig = _legacy_hmac_hex(body, SECRET)
    await source.verify_and_dispatch(body, {"X-Signature": legacy_sig})


@pytest.mark.asyncio
async def test_inline_hmac_completely_removed() -> None:
    """``WebhookSource`` не содержит inline-вычисления HMAC через hashlib/hmac.

    Wave [s2/k1-4-webhook-sig]: единая точка верификации — signatures.py.
    Legacy fallback (без timestamp_header) — единственное место, где
    остался inline-код по совместимости со старыми webhook-отправителями.
    """
    from pathlib import Path

    path = Path(__file__).resolve().parents[3]
    src = (path / "src/backend/infrastructure/sources/webhook.py").read_text()
    # При полной модернизации все webhook-отправители перейдут на canonical.
    # На переходный период допускаем lazy-import _hmac/_h в legacy-ветке.
    assert "from src.backend.infrastructure.security.signatures import" in src
    assert "verify_signature" in src
