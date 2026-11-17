"""Минимальный конфиг JupyterHub для prod-compose (инфраструктурный долг §18.7).

Подключается в ``ops/compose/docker-compose.prod.yml`` как
``/usr/local/etc/jupyterhub/jupyterhub_config.py`` — каталог конфигурации
JupyterHub по умолчанию (``sys.prefix/etc/jupyterhub``).

Назначение:
    * зарегистрировать API-токен приложения (``JUPYTER_HUB_API_TOKEN``)
      как токен пользователя-администратора — приложение ходит в
      ``/hub/api`` (см. ``src/backend/core/config/services/jupyter_hub.py``);
    * разрешить вход без пароля (DummyAuthenticator) — внутренний контур.

ВНИМАНИЕ (владелец инфраструктуры): аутентификация внутреннего контура —
    временная. Перед публикацией наружу заменить на корпоративный IdP
    (OIDC/LDAP) — см. ``docs/roadmap/OWNER_TASKS.md`` §18 (п. 7).
    Для фактического spawn ноутбуков нужен singleuser-образ и spawner
    (LocalProcessSpawner в этом образе не поднимает JupyterLab).
"""

import os

# ``get_config`` — магия JupyterHub (traitlets config API), её нет в модуле.
c = get_config()  # type: ignore[name-defined]  # noqa: F821

_api_token = os.environ.get("JUPYTER_HUB_API_TOKEN", "")
_api_user = os.environ.get("JUPYTER_HUB_API_USER", "admin")

if _api_token:
    # Токен пользователя: приложение использует его как bearer-токен
    # (``Authorization: token <value>``).
    c.JupyterHub.api_tokens = {_api_user: _api_token}

# Внутренний контур: вход без пароля.
c.Authenticator.allow_all = True
c.Authenticator.admin_users = {_api_user}
