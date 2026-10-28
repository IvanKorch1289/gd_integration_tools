"""Канонические правила распознавания секретов (ADR-0373).

Единый источник правды для гейтов конфигурации:

* ``tools/check_env_example.py`` — «в ``.env.example`` только секреты»
  (несекретный ключ или непустое значение секрета — нарушение);
* ``tools/config_audit.py`` — missing-secret (секретное поле Settings
  не документировано в ``.env.example``).

Модуль намеренно свободен от импортов ``src.*`` и внешних зависимостей:
его используют и CLI-инструменты, и юнит-тесты.

Правило «только секреты» и правило «значение — SecretStr» — разные вещи:

* ``is_secret_name`` отвечает на вопрос «это credential?», т.е. должно ли
  значение жить в ``.env`` (а не в YAML-профиле);
* ``is_secret_field`` дополнительно учитывает тип поля: ``SecretStr`` —
  всегда секрет, а ``int``/``bool``/``list``/``dict``/``Path`` — никогда,
  даже если имя похоже на секретное (``api_key_admin_roles``).
"""

from __future__ import annotations

import re

__all__ = (
    "NON_SECRET_TYPE_HINTS",
    "SECRET_NAME_MARKERS",
    "is_secret_field",
    "is_secret_name",
)

#: Имена полей/переменных, значения которых — чувствительные.
#:
#: Сопоставление: имя равно маркеру либо заканчивается на ``_<маркер>``.
#: ``secret_path`` / ``api_key_admin_roles`` / ``sanitize_api_keys`` под
#: правило НЕ подпадают — это пути и списки, а не значения credential'ов.
SECRET_NAME_MARKERS: frozenset[str] = frozenset(
    {
        "access_key",
        "accesskey",
        "api_key",
        "api_token",
        "apikey",
        "auth_token",
        "bind_password",
        "client_secret",
        "credential",
        "credentials",
        "login",
        "passphrase",
        "passwd",
        "password",
        "private_key",
        "pwd",
        "role_id",
        "secret",
        "secret_id",
        "secret_key",
        "secrets",
        "sentinel_password",
        "session_token",
        "shared_secret",
        "signature_secret",
        "token",
        "user_name",
        "username",
        "webhook_url",
    }
)

#: Типы, которые физически не могут хранить чувствительное значение.
NON_SECRET_TYPE_HINTS: tuple[str, ...] = (
    "int",
    "float",
    "bool",
    "list",
    "dict",
    "set",
    "Literal",
    "Path",
)


def is_secret_name(name: str) -> bool:
    """Считает ли имя поля/переменной секретом (эвристика по имени).

    Args:
        name: Имя поля (``api_key``) или переменной окружения (``SEC_API_KEY``).

    Returns:
        ``True``, если имя совпадает с маркером секрета или заканчивается
        на ``_<маркер>``.

    """
    lower = name.lower()
    return any(
        lower == marker or lower.endswith(f"_{marker}")
        for marker in SECRET_NAME_MARKERS
    )


def is_secret_field(name: str, annotation: str = "") -> bool:
    """Считает ли поле настроек секретом (по типу и/или имени).

    Args:
        name: Имя поля.
        annotation: Строковое представление аннотации типа (AST-скан).

    Returns:
        ``True``, если поле — ``SecretStr`` либо его имя соответствует
        каноническим маркерам. Поля с «несекретными» типами
        (``int``/``bool``/``list``/``dict``/``Path``/``Literal``) секретами
        не считаются независимо от имени.

    """
    if "SecretStr" in annotation:
        return True
    if annotation and any(
        re.search(rf"\b{hint}\b", annotation) for hint in NON_SECRET_TYPE_HINTS
    ):
        return False
    return is_secret_name(name)
