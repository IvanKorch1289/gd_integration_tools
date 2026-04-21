"""Bridge: VaultSecretRefresher ↔ ConnectorRegistry.

IL2.4 (ADR-022): при ротации Vault-секрета для заданного path автоматически
вызывать `ConnectorRegistry.reload(name)`, если клиент был зарегистрирован
с этим `vault_path`.

Использование (при startup приложения):

    from app.infrastructure.registry_vault_bridge import wire_vault_rotations

    wire_vault_rotations(
        registry=ConnectorRegistry.instance(),
        refresher=get_vault_refresher(),
    )

После wiring любой `registry.register(client, vault_path="database/creds/app")`
становится «живым»: ротация `database/creds/app` в Vault → автоматический
reload pool-а Postgres без рестарта приложения.

Коммерческий референс: MuleSoft Vault Secret Manager hot-refresh + runtime
Connection restart; WSO2 Secret Vault с Dynamic Endpoint refresh.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.config.vault_refresher import VaultSecretRefresher
    from app.infrastructure.registry import ConnectorRegistry


_logger = logging.getLogger(__name__)


def wire_vault_rotations(
    *,
    registry: "ConnectorRegistry",
    refresher: "VaultSecretRefresher",
) -> int:
    """Подписать `registry.reload(name)` на ротацию vault_path каждого клиента.

    Возвращает количество подписанных клиентов.

    Безопасно вызывать несколько раз — подписка идемпотентна: если клиент
    уже имел callback на этот path, второй не добавится (проверка по
    `client.name`).
    """
    wired = 0
    for name in registry.names():
        vault_path = registry.vault_path(name)
        if not vault_path:
            continue

        callback = _build_reload_callback(registry=registry, client_name=name)
        refresher.on_rotation(vault_path, callback)
        _logger.info(
            "connector wired to vault rotation",
            extra={"connector": name, "vault_path": vault_path},
        )
        wired += 1
    return wired


def _build_reload_callback(*, registry: "ConnectorRegistry", client_name: str):
    """Сформировать async-callback для конкретного клиента.

    Callback делает `registry.reload(name)` и логирует с явной привязкой
    client→path. Ошибки reload не пробрасываются — refresher сам логирует
    но продолжает обработку остальных path-ов.
    """

    async def _on_rotation(path: str, new_secrets: dict[str, Any]) -> None:
        _logger.info(
            "vault rotation detected — reloading connector",
            extra={
                "connector": client_name,
                "vault_path": path,
                "secret_keys": sorted(new_secrets.keys())[:10],  # не логируем values.
            },
        )
        try:
            duration_ms = await registry.reload(client_name)
            _logger.info(
                "connector reloaded after vault rotation",
                extra={"connector": client_name, "duration_ms": duration_ms},
            )
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "connector reload after vault rotation failed",
                extra={
                    "connector": client_name,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )

    return _on_rotation


__all__ = ("wire_vault_rotations",)
