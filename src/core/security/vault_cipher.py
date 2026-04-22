"""Envelope encryption через HashiCorp Vault Transit engine (IL-SEC2).

Vault Transit — это "encryption-as-a-service": приложение отправляет plaintext
в Vault, получает обратно ciphertext-строку формата ``vault:v<version>:<ct>``.
**Ключ шифрования никогда не покидает Vault.** Rotation и revocation —
централизованные команды в Vault, приложение перезагружать не нужно.

Паттерн singleton ``httpx.AsyncClient`` перенят из
``src/infrastructure/policy/opa.py::OPAClient`` (IL-CRIT1.4b): один клиент на
life-of-process, HTTP/2 + keepalive, graceful ``close()``.

**Политика отказа — fail-safe (НЕ fail-closed).** Encrypt/decrypt лежат на
критическом пути данных. "Тихо вернуть None" недопустимо: либо данные
корректно зашифрованы/расшифрованы, либо вызывающий сервис получает
``VaultCipherError`` и обязан обработать (reject запрос / dead-letter / alert).

Compliance покрытие: GDPR Art. 32, 152-ФЗ ст. 19, PCI DSS 3.5/3.6.

Пример использования::

    cipher = VaultTransitCipher(key_name="orders_response")
    ciphertext = await cipher.encrypt(b'{"passport": "1234 567890"}')
    # сохранить ciphertext в БД (LargeBinary или text)
    plaintext = await cipher.decrypt(ciphertext)
"""

from __future__ import annotations

import base64
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


__all__ = ("VaultCipherError", "VaultTransitCipher")


logger = logging.getLogger("security.vault_cipher")


class VaultCipherError(RuntimeError):
    """Ошибка при encrypt/decrypt/rotate через Vault Transit.

    Всегда поднимается наружу: вызывающий код должен решить, reject-нуть
    запрос, отправить в DLQ или сигнализировать оператору.
    """


class VaultTransitCipher:
    """Envelope encryption через Vault Transit engine.

    Особенности:
        * ключ шифрования живёт в Vault и никогда не попадает в RAM приложения;
        * ротация через ``rotate()`` — старые ciphertext-ы продолжают
          decrypt-иться (Vault помнит предыдущие версии ключа);
        * singleton httpx-клиент с HTTP/2 + pool → минимум latency overhead;
        * fail-safe: любая ошибка → ``VaultCipherError``.

    Параметры:
        key_name: логическое имя ключа в Vault (``transit/keys/<name>``).
            Ключ должен быть заранее создан администратором Vault
            (``vault write -f transit/keys/<name>``).
        mount_path: путь mount-а engine-а, default ``transit``.
        vault_addr: URL Vault, default из env ``VAULT_ADDR``.
        vault_token: токен приложения, default из env ``VAULT_TOKEN``.
            В prod-окружении рекомендуется AppRole / K8s auth вместо
            long-lived token-а.
        timeout: секунд на HTTP-вызов (encrypt/decrypt — быстрый путь).
        max_connections / max_keepalive_connections: pool-параметры.
    """

    def __init__(
        self,
        key_name: str,
        *,
        mount_path: str = "transit",
        vault_addr: str | None = None,
        vault_token: str | None = None,
        timeout: float = 2.0,
        max_connections: int = 32,
        max_keepalive_connections: int = 16,
    ) -> None:
        self.key_name = key_name
        self.mount_path = mount_path.strip("/")
        self.vault_addr = (
            vault_addr or os.getenv("VAULT_ADDR") or "http://localhost:8200"
        ).rstrip("/")
        self.vault_token = vault_token or os.getenv("VAULT_TOKEN") or ""
        self.timeout = timeout
        self._max_connections = max_connections
        self._max_keepalive = max_keepalive_connections
        self._client: "httpx.AsyncClient | None" = None

        if not self.vault_token:
            logger.warning(
                "VaultTransitCipher создан без VAULT_TOKEN — encrypt/decrypt "
                "будут падать с VaultCipherError до конфигурации auth."
            )

    # ------------------------------------------------------------------ infra

    def _ensure_client(self) -> "httpx.AsyncClient":
        """Lazy-init singleton httpx-клиента (pattern из OPAClient)."""
        if self._client is None:
            import httpx

            limits = httpx.Limits(
                max_connections=self._max_connections,
                max_keepalive_connections=self._max_keepalive,
                keepalive_expiry=30.0,
            )
            headers = {"X-Vault-Token": self.vault_token} if self.vault_token else {}
            self._client = httpx.AsyncClient(
                base_url=self.vault_addr,
                http2=True,
                timeout=self.timeout,
                limits=limits,
                headers=headers,
            )
            logger.debug(
                "VaultTransitCipher initialized (mount=%s, key=%s, pool=%d/%d)",
                self.mount_path,
                self.key_name,
                self._max_connections,
                self._max_keepalive,
            )
        return self._client

    async def close(self) -> None:
        """Graceful shutdown httpx клиента (идемпотентно)."""
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None

    # ---------------------------------------------------------------- encrypt

    async def encrypt(self, plaintext: bytes | str) -> str:
        """Шифрует bytes/str и возвращает строку ``vault:v<N>:<ciphertext>``.

        Vault ожидает base64-закодированный plaintext в JSON-payload-е.

        :raises VaultCipherError: при любой ошибке сети / HTTP 4xx-5xx /
            неожиданного формата ответа.
        """
        if isinstance(plaintext, str):
            plaintext = plaintext.encode("utf-8")
        b64_pt = base64.b64encode(plaintext).decode("ascii")
        path = f"/v1/{self.mount_path}/encrypt/{self.key_name}"
        client = self._ensure_client()
        try:
            resp = await client.post(path, json={"plaintext": b64_pt})
        except Exception as exc:  # noqa: BLE001 — сеть/TLS/timeout
            raise VaultCipherError(f"vault encrypt network error: {exc}") from exc
        if resp.status_code != 200:
            raise VaultCipherError(
                f"vault encrypt HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            ciphertext = resp.json()["data"]["ciphertext"]
        except (KeyError, ValueError) as exc:
            raise VaultCipherError(
                f"vault encrypt bad response: {resp.text[:200]}"
            ) from exc
        if not isinstance(ciphertext, str) or not ciphertext.startswith("vault:"):
            raise VaultCipherError(
                f"vault encrypt returned invalid ciphertext: {ciphertext!r}"
            )
        return ciphertext

    # ---------------------------------------------------------------- decrypt

    async def decrypt(self, ciphertext: str) -> bytes:
        """Расшифровывает ``vault:v<N>:<ct>`` → plaintext bytes.

        :raises VaultCipherError: при любой ошибке сети / HTTP / base64.
        """
        if not isinstance(ciphertext, str) or not ciphertext.startswith("vault:"):
            raise VaultCipherError(
                f"invalid ciphertext format (expected 'vault:v<N>:...'): "
                f"{ciphertext!r}"
            )
        path = f"/v1/{self.mount_path}/decrypt/{self.key_name}"
        client = self._ensure_client()
        try:
            resp = await client.post(path, json={"ciphertext": ciphertext})
        except Exception as exc:  # noqa: BLE001
            raise VaultCipherError(f"vault decrypt network error: {exc}") from exc
        if resp.status_code != 200:
            raise VaultCipherError(
                f"vault decrypt HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            b64_pt = resp.json()["data"]["plaintext"]
        except (KeyError, ValueError) as exc:
            raise VaultCipherError(
                f"vault decrypt bad response: {resp.text[:200]}"
            ) from exc
        try:
            return base64.b64decode(b64_pt)
        except Exception as exc:  # noqa: BLE001
            raise VaultCipherError(f"vault decrypt base64 error: {exc}") from exc

    # ----------------------------------------------------------------- rotate

    async def rotate(self) -> int:
        """Ротирует ключ в Vault, возвращает номер новой версии.

        Старые ciphertext-ы продолжают decrypt-иться (Vault хранит архив
        версий по умолчанию). При необходимости `rewrap` можно вызвать
        отдельно (не в scope IL-SEC2-phase-1).

        :raises VaultCipherError: при ошибке вызова rotate/reading version.
        """
        path = f"/v1/{self.mount_path}/keys/{self.key_name}/rotate"
        client = self._ensure_client()
        try:
            resp = await client.post(path, json={})
        except Exception as exc:  # noqa: BLE001
            raise VaultCipherError(f"vault rotate network error: {exc}") from exc
        if resp.status_code not in (200, 204):
            raise VaultCipherError(
                f"vault rotate HTTP {resp.status_code}: {resp.text[:200]}"
            )
        # Чтобы узнать новую версию — читаем метаданные ключа.
        read_path = f"/v1/{self.mount_path}/keys/{self.key_name}"
        try:
            meta_resp = await client.get(read_path)
        except Exception as exc:  # noqa: BLE001
            raise VaultCipherError(f"vault read-key network error: {exc}") from exc
        if meta_resp.status_code != 200:
            raise VaultCipherError(
                f"vault read-key HTTP {meta_resp.status_code}: "
                f"{meta_resp.text[:200]}"
            )
        try:
            latest = int(meta_resp.json()["data"]["latest_version"])
        except (KeyError, ValueError, TypeError) as exc:
            raise VaultCipherError(
                f"vault read-key bad response: {meta_resp.text[:200]}"
            ) from exc
        logger.info(
            "Vault Transit key rotated: %s → v%d", self.key_name, latest
        )
        return latest
