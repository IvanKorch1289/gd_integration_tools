"""Банковская безопасность: ГОСТ-подпись, HSM, tx-signing, anti-fraud rules.

Модуль предоставляет интерфейсы — реальные реализации подключаются через
DI (Vault для ключей, HSM через PKCS#11, ФЗ-63 криптопровайдеры).

ВАЖНО: Никаких настоящих криптооперций здесь нет. Только контракты —
чтобы бизнес-код не зависел от конкретного крипто-провайдера.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

__all__ = (
    "CryptoProvider",
    "DummyCryptoProvider",
    "HsmBackend",
    "SoftwareHsmBackend",
    "TxSigner",
    "AntiFraudRule",
    "AntiFraudEngine",
    "SignedTransaction",
)


class CryptoProvider(Protocol):
    """Контракт крипто-провайдера (ГОСТ/RSA/ECDSA)."""

    def sign(self, data: bytes, key_id: str) -> bytes: ...
    def verify(self, data: bytes, signature: bytes, key_id: str) -> bool: ...
    def hash(self, data: bytes) -> bytes: ...


class DummyCryptoProvider:
    """Только для dev/test. В production подменяется ГОСТ-провайдером через DI.

    Использует HMAC-SHA256 — НЕ для реальных банковских операций.
    """

    def __init__(self, hmac_secret: bytes | None = None) -> None:
        self._secret = hmac_secret or os.urandom(32)

    def sign(self, data: bytes, key_id: str) -> bytes:
        return hmac.new(self._secret + key_id.encode(), data, hashlib.sha256).digest()

    def verify(self, data: bytes, signature: bytes, key_id: str) -> bool:
        return hmac.compare_digest(self.sign(data, key_id), signature)

    def hash(self, data: bytes) -> bytes:
        return hashlib.sha256(data).digest()


class HsmBackend(ABC):
    """PKCS#11 HSM бэкенд. Реальная реализация — через python-pkcs11."""

    @abstractmethod
    def load_key(self, key_id: str) -> Any: ...

    @abstractmethod
    def sign_with_hsm(self, data: bytes, key_id: str) -> bytes: ...


class SoftwareHsmBackend(HsmBackend):
    """Программный HSM-эмулятор для dev. В production — HSMBackend через PKCS#11."""

    def __init__(self, crypto: CryptoProvider) -> None:
        self._crypto = crypto

    def load_key(self, key_id: str) -> Any:
        return key_id

    def sign_with_hsm(self, data: bytes, key_id: str) -> bytes:
        return self._crypto.sign(data, key_id)


@dataclass(frozen=True)
class SignedTransaction:
    """Транзакция + подпись + метаданные для аудита."""

    payload: bytes
    signature: bytes
    key_id: str
    signed_at: datetime
    algorithm: str = "GOST-R-34.10-2012"


class TxSigner:
    """Подписание банковских транзакций. Алгоритм указывается в конфиге.

    Подпись + payload + timestamp кладутся в SignedTransaction,
    который затем передаётся в audit log и в outbox-таблицу для отправки.
    """

    def __init__(
        self, crypto: CryptoProvider, algorithm: str = "GOST-R-34.10-2012"
    ) -> None:
        self._crypto = crypto
        self._algorithm = algorithm

    def sign(self, payload: bytes, key_id: str) -> SignedTransaction:
        signature = self._crypto.sign(payload, key_id)
        return SignedTransaction(
            payload=payload,
            signature=signature,
            key_id=key_id,
            signed_at=datetime.now(timezone.utc),
            algorithm=self._algorithm,
        )

    def verify(self, tx: SignedTransaction) -> bool:
        return self._crypto.verify(tx.payload, tx.signature, tx.key_id)


@dataclass
class AntiFraudRule:
    """Правило антифрода: predicate + severity.

    predicate получает dict с транзакцией и возвращает True, если правило сработало.
    """

    name: str
    predicate: Any  # Callable[[dict[str, Any]], bool]
    severity: str = "warn"  # warn | block
    reason: str = ""


class AntiFraudEngine:
    """Движок правил антифрода. Возвращает список сработавших правил.

    Реальная ML-модель подключается отдельно (см. services/anomaly_detector.py);
    этот движок — детерминистические правила.
    """

    def __init__(self, rules: list[AntiFraudRule] | None = None) -> None:
        self._rules: list[AntiFraudRule] = list(rules or [])

    def register(self, rule: AntiFraudRule) -> None:
        self._rules.append(rule)

    def evaluate(self, tx: dict[str, Any]) -> list[AntiFraudRule]:
        triggered = []
        for rule in self._rules:
            try:
                if rule.predicate(tx):
                    triggered.append(rule)
            except Exception:  # noqa: BLE001
                continue
        return triggered

    def is_blocked(self, tx: dict[str, Any]) -> bool:
        return any(r.severity == "block" for r in self.evaluate(tx))
