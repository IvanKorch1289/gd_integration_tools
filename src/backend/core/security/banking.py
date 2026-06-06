"""Банковская безопасность: ГОСТ-подпись, HSM, tx-signing, anti-fraud rules.

Модуль предоставляет интерфейсы — реальные реализации подключаются через
DI (Vault для ключей, HSM через PKCS#11, ФЗ-63 криптопровайдеры).

ВАЖНО: Никаких настоящих криптооперций здесь нет. Только контракты —
чтобы бизнес-код не зависел от конкретного крипто-провайдера.
"""
from __future__ import annotations
import hashlib
import hmac
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
logger = logging.getLogger(__name__)
__all__ = ('AntiFraudEngine', 'AntiFraudRule', 'CryptoProvider', 'DummyCryptoProvider', 'HsmBackend', 'SignedTransaction', 'SoftwareHsmBackend', 'TxSigner')

class CryptoProvider(Protocol):
    """Контракт крипто-провайдера (ГОСТ/RSA/ECDSA)."""

    def sign(self, data: bytes, key_id: str) -> bytes:
        """Выполнить операцию sign."""
        ...

    def verify(self, data: bytes, signature: bytes, key_id: str) -> bool:
        """Выполнить операцию verify."""
        ...

    def hash(self, data: bytes) -> bytes:
        """Выполнить операцию hash."""
        ...

class DummyCryptoProvider:
    """Только для dev/test. В production подменяется ГОСТ-провайдером через DI.

    Использует HMAC-SHA256 — НЕ для реальных банковских операций.
    """

    def __init__(self, hmac_secret: bytes | None=None) -> None:
        """Выполнить операцию   init  ."""
        self._secret = hmac_secret or os.urandom(32)

    def sign(self, data: bytes, key_id: str) -> bytes:
        """Выполнить операцию sign."""
        return hmac.new(self._secret + key_id.encode(), data, hashlib.sha256).digest()

    def verify(self, data: bytes, signature: bytes, key_id: str) -> bool:
        """Выполнить операцию verify."""
        return hmac.compare_digest(self.sign(data, key_id), signature)

    def hash(self, data: bytes) -> bytes:
        """Выполнить операцию hash."""
        return hashlib.sha256(data).digest()

class HsmBackend(ABC):
    """PKCS#11 HSM бэкенд. Реальная реализация — через python-pkcs11."""

    @abstractmethod
    def load_key(self, key_id: str) -> Any:
        """Выполнить операцию load key."""
        ...

    @abstractmethod
    def sign_with_hsm(self, data: bytes, key_id: str) -> bytes:
        """Выполнить операцию sign with hsm."""
        ...

class SoftwareHsmBackend(HsmBackend):
    """Программный HSM-эмулятор для dev. В production — HSMBackend через PKCS#11."""

    def __init__(self, crypto: CryptoProvider) -> None:
        """Выполнить операцию   init  ."""
        self._crypto = crypto

    def load_key(self, key_id: str) -> Any:
        """Выполнить операцию load key."""
        return key_id

    def sign_with_hsm(self, data: bytes, key_id: str) -> bytes:
        """Выполнить операцию sign with hsm."""
        return self._crypto.sign(data, key_id)

@dataclass(frozen=True)
class SignedTransaction:
    """Транзакция + подпись + метаданные для аудита."""
    payload: bytes
    signature: bytes
    key_id: str
    signed_at: datetime
    algorithm: str = 'GOST-R-34.10-2012'

class TxSigner:
    """Подписание банковских транзакций. Алгоритм указывается в конфиге.

    Подпись + payload + timestamp кладутся в SignedTransaction,
    который затем передаётся в audit log и в outbox-таблицу для отправки.
    """

    def __init__(self, crypto: CryptoProvider, algorithm: str='GOST-R-34.10-2012') -> None:
        """Выполнить операцию   init  ."""
        self._crypto = crypto
        self._algorithm = algorithm

    def sign(self, payload: bytes, key_id: str) -> SignedTransaction:
        """Выполнить операцию sign."""
        signature = self._crypto.sign(payload, key_id)
        return SignedTransaction(payload=payload, signature=signature, key_id=key_id, signed_at=datetime.now(UTC), algorithm=self._algorithm)

    def verify(self, tx: SignedTransaction) -> bool:
        """Выполнить операцию verify."""
        return self._crypto.verify(tx.payload, tx.signature, tx.key_id)

@dataclass
class AntiFraudRule:
    """Правило антифрода: predicate + severity.

    predicate получает dict с транзакцией и возвращает True, если правило сработало.
    """
    name: str
    predicate: Any
    severity: str = 'warn'
    reason: str = ''

class AntiFraudEngine:
    """Движок правил антифрода. Возвращает список сработавших правил.

    Реальная ML-модель подключается отдельно (см. services/anomaly_detector.py);
    этот движок — детерминистические правила.
    """

    def __init__(self, rules: list[AntiFraudRule] | None=None) -> None:
        """Выполнить операцию   init  ."""
        self._rules: list[AntiFraudRule] = list(rules or [])

    def register(self, rule: AntiFraudRule) -> None:
        """Выполнить операцию register."""
        self._rules.append(rule)

    def evaluate(self, tx: dict[str, Any]) -> list[AntiFraudRule]:
        """Выполнить операцию evaluate."""
        triggered = []
        for rule in self._rules:
            try:
                if rule.predicate(tx):
                    triggered.append(rule)
            except Exception as _:
                logger.debug('anti-fraud rule predicate raised; rule skipped', exc_info=True)
                continue
        return triggered

    def is_blocked(self, tx: dict[str, Any]) -> bool:
        """Проверить условие is blocked."""
        return any((r.severity == 'block' for r in self.evaluate(tx)))