"""Сервис User (миграция из ядра — Sprint 7, R-V15-16).

S58 W6: расширен для unified auth (password + LDAP) с auto-provisioning.

* :meth:`UserService.login_with_method` — единый entry point
  (dispatch по ``method`` — ``"password"`` / ``"ldap"``);
* :meth:`UserService._login_password` — legacy password auth
  (``@deprecated`` — будет удалено когда фронт полностью перейдёт на LDAP);
* :meth:`UserService._login_ldap` — LDAP auth через
  :class:`AdDirectoryClient` с auto-provisioning локального User
  при первом успешном bind;
* :meth:`UserService._provision_ldap_user` — get-or-create User
  по username из LDAP attrs (sync email при каждом login);
* :meth:`UserService.login` — DEPRECATED, оставлен для backward compat
  (вызывает :meth:`_login_password` + warning).

Каноническое расположение в V11 plugin layout. Старый модуль
``src.backend.services.core.users`` сохраняется как backward-compat
shim и эмитит DeprecationWarning.
"""

from __future__ import annotations

import importlib
import warnings
from typing import Any, Literal

from src.backend.core.auth.ad_directory import AdAuthError, AdSearchEntry
from src.backend.core.errors import ServiceError
from src.backend.core.interfaces.repositories import UserRepositoryProtocol
from src.backend.core.services.base_service import BaseService
from extensions.core_entities.users.schemas.route import (  # S168 W15-17 P2-10
    UserSchemaIn,
    UserSchemaOut,
    UserVersionSchemaOut,
)

__all__ = ("UserService", "get_user_service", "AuthMethod")


# === Auth method type (Literal для type hints + OpenAPI generation) ===

AuthMethod = Literal["password", "ldap"]


_REPO_USERS_MOD = "extensions.core_entities.users.repositories.users"


class UserService(
    BaseService[
        UserRepositoryProtocol, UserSchemaOut, UserSchemaIn, UserVersionSchemaOut
    ]
):
    """Сервис для работы с пользователями (создание + аутентификация)."""

    async def _get_user_by_username(self, data: dict[str, Any]) -> Any:
        """Поиск пользователя по имени.

        Args:
            data: Словарь с ``username``.

        Returns:
            Объект пользователя или ``None``.

        Raises:
            ServiceError: Если произошла ошибка в репозитории.
        """
        try:
            return await self.repo.get_by_username(data=data)
        except Exception as exc:
            raise ServiceError from exc

    async def add(self, data: dict[str, Any]) -> UserSchemaOut | None:
        """Добавляет нового пользователя.

        Args:
            data: Данные для создания пользователя.

        Returns:
            ``UserSchemaOut`` со созданным пользователем.

        Raises:
            ValueError: Если пользователь с таким логином уже существует.
            ServiceError: Любая иная ошибка добавления.
        """
        try:
            user = await self._get_user_by_username(data=data)
            if user:
                raise ValueError("The user with the specified login already exists.")
            return await super().add(data=data)
        except ValueError:
            raise
        except Exception as exc:
            raise ServiceError from exc

    # === Legacy password auth (DEPRECATED, S58 W6) ===

    async def login(self, data: dict[str, Any]) -> bool:
        """DEPRECATED: используйте :meth:`login_with_method`.

        Password-based auth — оставлен для backward compat (S58 W6).
        Помечен ``DeprecationWarning`` при вызове. Будет удалён когда
        фронт полностью перейдёт на LDAP (S59+).

        Args:
            data: Словарь с ``username`` и ``password``.

        Returns:
            ``True`` если credentials валидны, иначе ``False``.

        Raises:
            ServiceError: Если произошла ошибка проверки.
        """
        warnings.warn(
            "UserService.login() is deprecated; use login_with_method() instead. "
            "See ADR-0085 (S58 W6) for migration plan.",
            DeprecationWarning,
            stacklevel=2,
        )
        user = await self._login_password(
            username=data.get("username", ""), password=data.get("password", "")
        )
        return user is not None

    # === Unified auth dispatch (S58 W6) ===

    async def login_with_method(
        self, *, method: AuthMethod, username: str, password: str | None = None
    ) -> Any:
        """Единый entry point для аутентификации (S58 W6).

        Dispatch по ``method``:
        * ``"password"`` — legacy password auth (deprecated);
        * ``"ldap"`` — bind через :class:`AdDirectoryClient` +
          auto-provisioning локального User.

        Args:
            method: ``"password"`` или ``"ldap"``.
            username: Логин (для password) или userPrincipalName
                (для LDAP, зависит от ``LDAP_USER_ID_ATTRIBUTE``).
            password: Plain-text пароль (для password и LDAP bind).

        Returns:
            Локальный User instance (модель БД) при успехе; ``None`` при
            неверных credentials.

        Raises:
            ValueError: Неизвестный ``method``.
            ServiceError: Ошибка сервиса / репозитория.
            AdAuthError: LDAP ошибка (server unreachable, etc.).
        """
        if method == "password":
            return await self._login_password(
                username=username, password=password or ""
            )
        if method == "ldap":
            return await self._login_ldap(username=username, password=password or "")
        raise ValueError(
            f"Unknown auth method: {method!r}. Supported: 'password', 'ldap'."
        )

    async def _login_password(self, *, username: str, password: str) -> Any:
        """Legacy password-based auth (DEPRECATED).

        Returns:
            User instance при валидных credentials, иначе ``None``.
        """
        if not username or not password:
            return None
        try:
            user = await self.repo.get_by_username(data={"username": username})
        except Exception as exc:
            raise ServiceError from exc
        if user and user.verify_password(password=password):
            return user
        return None

    async def _login_ldap(self, *, username: str, password: str) -> Any:
        """LDAP-based auth с auto-provisioning (S58 W6).

        Flow:
        1. Получить singleton :class:`AdDirectoryClient` через
           :func:`get_ad_client` (lazy import для избежания circular);
        2. ``find_user(username)`` — ищет userPrincipalName/sAMAccountName
           в AD (search с service-account bind);
        3. ``validate_credentials(user_dn, password)`` — bind от имени
           пользователя; неуспех = неверный пароль → ``None``;
        4. ``_provision_ldap_user(ad_user)`` — get-or-create локальный
           User + sync email/display_name при каждом login.

        Args:
            username: UserPrincipalName / sAMAccountName в AD.
            password: Plain-text password для bind.

        Returns:
            Локальный User instance при успешном bind, иначе ``None``.

        Raises:
            AdAuthError: LDAP server unreachable / ldap3 not installed /
                AD attribute error.
            ServiceError: Ошибка репозитория.
        """
        # Lazy import: ldap_client_factory живёт в core.auth
        from src.backend.core.auth.ldap_client_factory import get_ad_client

        if not username or not password:
            return None

        ad_client = get_ad_client()
        if ad_client is None:
            # LDAP не сконфигурирован или feature flag OFF.
            # Это NOT user-error → caller решает (fallback на password / 503).
            raise AdAuthError(
                "LDAP auth is not enabled or not configured "
                "(check feature_flags.saml_ad_login_enabled and LDAP_*)"
            )

        if not ad_client.is_available():
            raise AdAuthError(
                "ldap3 library is not installed; pip install ldap3 "
                "(or uv sync --extra dsl-extras-3)"
            )

        # 1. Find user in AD
        ad_user = await ad_client.find_user(login=username)
        if ad_user is None:
            return None

        # 2. Validate credentials (bind)
        try:
            valid = await ad_client.validate_credentials(
                user_dn=ad_user.dn, password=password
            )
        except AdAuthError:
            return None
        if not valid:
            return None

        # 3. Auto-provision local User + sync attrs
        return await self._provision_ldap_user(ad_user)

    async def _provision_ldap_user(self, ad_user: AdSearchEntry) -> Any:
        """Get-or-create локальный User из AD search result + sync attrs.

        Sync logic (на каждом login):
        * email (если изменилось в AD) — обновляем;
        * display_name (если есть в AD attrs) — обновляем ``first_name`` /
          ``last_name`` через parsing ``displayName``;
        * is_active — НЕ меняем (admin контроль локально).

        Returns:
            User instance (existing or newly created).
        """
        try:
            existing = await self.repo.get_by_username(
                data={"username": _extract_username(ad_user)}
            )
        except Exception as exc:
            raise ServiceError from exc

        ad_email = ad_user.attributes.get("mail") or ad_user.attributes.get("email")
        ad_display_name = (
            ad_user.attributes.get("displayName")
            or ad_user.attributes.get("cn")
            or _extract_username(ad_user)
        )

        if existing is not None:
            # Sync attrs (email + display_name)
            dirty = False
            if ad_email and existing.email != ad_email:
                existing.email = ad_email  # type: ignore[attr-defined]
                dirty = True
            # displayName parsing (best-effort, не критично)
            if isinstance(ad_display_name, str) and " " in ad_display_name:
                parts = ad_display_name.split(maxsplit=1)
                if hasattr(existing, "first_name") and existing.first_name != parts[0]:  # type: ignore[attr-defined]
                    existing.first_name = parts[0]  # type: ignore[attr-defined]
                    dirty = True
                if (
                    hasattr(existing, "last_name")
                    and len(parts) > 1
                    and existing.last_name != parts[1]  # type: ignore[attr-defined]
                ):
                    existing.last_name = parts[1]  # type: ignore[attr-defined]
                    dirty = True
            if dirty:
                try:
                    await self.repo.update(existing)
                except Exception as exc:
                    raise ServiceError from exc
            return existing

        # Auto-provision new user
        username = _extract_username(ad_user)
        first, _, last = (
            ad_display_name.partition(" ")
            if isinstance(ad_display_name, str)
            else ("", "", "")
        )
        new_data: dict[str, Any] = {
            "username": username,
            "email": ad_email or f"{username}@unknown.local",
            "is_active": True,
            "is_superuser": False,
            # НЕ задаём password — LDAP-only user, локальный password не используется
        }
        if first:
            new_data["first_name"] = first
        if last:
            new_data["last_name"] = last
        try:
            return await self.repo.add(new_data)
        except Exception as exc:
            raise ServiceError from exc


def _extract_username(ad_user: AdSearchEntry) -> str:
    """Извлекает local username из :class:`AdSearchEntry` (S58 W6c).

    Priority:
    1. ``sAMAccountName`` (Windows login, no domain) — preferred;
    2. ``userPrincipalName`` (alice@example.com) → strip domain;
    3. First ``CN=`` из DN — fallback.

    Returns:
        Non-empty string. Caller raises если пусто (должно быть impossible
        для AD user).
    """
    attrs = ad_user.attributes
    sam = attrs.get("sAMAccountName")
    if isinstance(sam, str) and sam:
        return sam
    upn = attrs.get("userPrincipalName")
    if isinstance(upn, str) and upn:
        # userPrincipalName = alice@example.com → local = alice
        return upn.split("@", 1)[0]
    cn = attrs.get("cn")
    if isinstance(cn, str) and cn:
        return cn
    # Fallback: first CN from DN (e.g., "CN=alice,OU=..." → "alice")
    if ad_user.dn.upper().startswith("CN="):
        cn_from_dn = ad_user.dn.split(",", 1)[0][3:]
        if cn_from_dn:
            return cn_from_dn
    return ad_user.dn  # Last resort (должно быть impossible)


_user_service_instance: UserService | None = None


def get_user_service() -> UserService:
    """Возвращает singleton экземпляр :class:`UserService`."""
    global _user_service_instance
    if _user_service_instance is None:
        repo = importlib.import_module(_REPO_USERS_MOD).get_user_repo()
        _user_service_instance = UserService(
            repo=repo,
            request_schema=UserSchemaIn,
            response_schema=UserSchemaOut,
            version_schema=UserVersionSchemaOut,
        )
    return _user_service_instance
