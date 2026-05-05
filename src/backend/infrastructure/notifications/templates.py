"""Template Registry с Jinja2 + i18n (IL2.2).

`TemplateRegistry` — in-memory хранилище шаблонов для уведомлений.
Ключ — `template_key` (например, `kyc_approved`). Для каждого ключа —
`templates` per locale (`ru`, `en`) с `subject` и `body`.

Безопасность: `Environment(autoescape=select_autoescape(["html", "xml"]))`
включён по умолчанию — защита от XSS при отправке HTML-email. Сервисы
НЕ должны регистрировать templates от user-input (только из controlled
localization catalogs).

Коммерческий референс: MuleSoft Email Connector + Velocity templates,
WSO2 Template Mediator, TIBCO NotifyMessage templates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final

from jinja2 import Environment, StrictUndefined, select_autoescape

_logger = logging.getLogger(__name__)


DEFAULT_LOCALE: Final = "ru"
SUPPORTED_LOCALES: Final = ("ru", "en")


@dataclass(slots=True)
class TemplateSpec:
    """Один шаблон сообщения на конкретную локаль."""

    subject: str
    body: str


@dataclass(slots=True)
class TemplateEntry:
    """Регистрация одного template_key — все локали и ограничения каналов."""

    key: str
    #: locale → TemplateSpec. Минимум один язык обязателен.
    locales: dict[str, TemplateSpec] = field(default_factory=dict)
    #: Если не пусто — список channel_kind, для которых template применим.
    #: Пустой = любой канал. Полезно чтобы не слать HTML-письмо в SMS.
    allowed_channels: tuple[str, ...] = ()


class TemplateNotFoundError(KeyError):
    """Запрошен неизвестный template_key / locale."""


class TemplateRegistry:
    """In-memory реестр Jinja2-шаблонов для уведомлений.

    Не persistent — при рестарте процесса регистрация должна повторяться
    (через `register_default_templates()` в startup или через чтение из
    локализационных каталогов). Persistence опционально добавится в IL3 через
    Postgres-бэкенд.
    """

    _instance: "TemplateRegistry | None" = None

    def __init__(self) -> None:
        self._entries: dict[str, TemplateEntry] = {}
        # Окружение с authoescape — при рендеринге body внутрь HTML-email
        # '{{user_input}}' будет экранирован.
        self._env = Environment(
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,  # bug-catching: отсутствующая переменная → error, не "Undefined"
            keep_trailing_newline=True,
        )

    @classmethod
    def instance(cls) -> "TemplateRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # -- Регистрация ---------------------------------------------------

    def register(
        self,
        *,
        key: str,
        templates: dict[str, dict[str, str]],
        allowed_channels: tuple[str, ...] = (),
    ) -> None:
        """Зарегистрировать шаблон под ``key`` с набором локалей.

        Формат ``templates``:

            {
                "ru": {"subject": "...", "body": "..."},
                "en": {"subject": "...", "body": "..."},
            }

        Каждая локаль обязана иметь поля `subject` и `body` (pydantic не
        используется — простая валидация dict-ом, чтобы держать модуль
        лёгким и быстрым).
        """
        if not templates:
            raise ValueError(f"Template '{key}': at least one locale required")
        locales: dict[str, TemplateSpec] = {}
        for locale, spec in templates.items():
            if "subject" not in spec or "body" not in spec:
                raise ValueError(
                    f"Template '{key}' locale '{locale}': "
                    f"'subject' and 'body' are required"
                )
            locales[locale] = TemplateSpec(subject=spec["subject"], body=spec["body"])
        self._entries[key] = TemplateEntry(
            key=key, locales=locales, allowed_channels=allowed_channels
        )
        _logger.debug(
            "template registered",
            extra={
                "key": key,
                "locales": list(locales.keys()),
                "allowed_channels": allowed_channels,
            },
        )

    # -- Rendering -----------------------------------------------------

    def render(
        self,
        *,
        key: str,
        locale: str = DEFAULT_LOCALE,
        context: dict[str, Any] | None = None,
        channel_kind: str | None = None,
    ) -> TemplateSpec:
        """Отрендерить subject+body по ключу и локали.

        Fallback на `DEFAULT_LOCALE`, если конкретная локаль не найдена.
        Если channel_kind не в `allowed_channels` — `ValueError`.
        """
        entry = self._entries.get(key)
        if entry is None:
            raise TemplateNotFoundError(f"Template '{key}' not registered")

        if (
            channel_kind
            and entry.allowed_channels
            and channel_kind not in entry.allowed_channels
        ):
            raise ValueError(
                f"Template '{key}' not allowed for channel '{channel_kind}'. "
                f"Allowed: {', '.join(entry.allowed_channels)}"
            )

        spec = entry.locales.get(locale) or entry.locales.get(DEFAULT_LOCALE)
        if spec is None:
            raise TemplateNotFoundError(
                f"Template '{key}' has no locale '{locale}' or default '{DEFAULT_LOCALE}'"
            )

        ctx = context or {}
        try:
            subject = self._env.from_string(spec.subject).render(**ctx)
            body = self._env.from_string(spec.body).render(**ctx)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                f"Template '{key}' rendering failed: {type(exc).__name__}: {exc}"
            ) from exc
        return TemplateSpec(subject=subject, body=body)

    # -- Introspection -------------------------------------------------

    def keys(self) -> list[str]:
        return sorted(self._entries.keys())

    def locales_of(self, key: str) -> list[str]:
        entry = self._entries.get(key)
        return sorted(entry.locales.keys()) if entry else []

    def is_registered(self, key: str) -> bool:
        return key in self._entries


def get_template_registry() -> TemplateRegistry:
    """Глобальный helper для бизнес-кода."""
    return TemplateRegistry.instance()


__all__ = (
    "TemplateRegistry",
    "TemplateEntry",
    "TemplateSpec",
    "TemplateNotFoundError",
    "get_template_registry",
    "DEFAULT_LOCALE",
    "SUPPORTED_LOCALES",
)
