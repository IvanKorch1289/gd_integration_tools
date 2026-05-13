"""Pytest entry-point плагин для автоматической регистрации testkit-фикстур.

Регистрируется через ``[project.entry-points."pytest11"] testkit = "testkit.pytest_plugin"``
в ``pyproject.toml``. После установки пакета pytest автоматически загружает
этот модуль и подхватывает все фикстуры перечисленных sub-модулей.

Модули с heavy-зависимостями (testcontainers, temporal SDK и т.п.) не
импортируются на top-level — их фикстуры используют lazy-import внутри тела
функции и вызывают ``pytest.importorskip()`` при необходимости.
"""

from __future__ import annotations

# Список sub-модулей testkit, экспортирующих pytest-фикстуры.
# pytest читает этот кортеж и регистрирует все @pytest.fixture из указанных
# модулей так, как если бы они были объявлены в conftest.py.
pytest_plugins: tuple[str, ...] = (
    "testkit.auth_fixtures",
    "testkit.mtls_fixtures",
)
