# Getting Started

Минимальный путь к работающему dev-light backend за 5 минут.

## Предусловия

* Python 3.14+;
* `uv` установлен (`pipx install uv`);
* git clone репозитория.

## Шаги

```{tabs}

.. tab:: Linux/macOS

    .. code-block:: bash

        cd gd_integration_tools
        uv sync --extra dev-light --dev
        make dev-light

.. tab:: Windows (PowerShell)

    .. code-block:: pwsh

        cd gd_integration_tools
        uv sync --extra dev-light --dev
        $env:APP_PROFILE = "dev_light"
        uv run python manage.py serve

```

После старта откройте http://127.0.0.1:8000/api/v1/health — ответ
`{"status": "ok"}` подтверждает, что backend работает.

## Что дальше

* [Build first action](01_build_first_action.md) — добавляем первую action и регистрируем route.
* [First plugin](02_first_plugin.md) — собираем V11-плагин через `make new-plugin`.
