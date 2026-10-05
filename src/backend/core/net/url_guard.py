"""SSRF-guard для исходящей навигации (F-AP1, CRITICAL).

Единственный канонический способ проверить URL **до** того, как он уйдёт
в браузер, HTTP-клиент или другой сетевой стек. Раньше проверка жила
в ``dsl/engine/processors/scraping.py`` как приватный ``_validate_url`` и
покрывала только HTTP-выборку: браузерная навигация (11 точек
``page.goto``) не проверялась вовсе.

Что закрывает этот модуль (всё это проходило раньше):

* ``file:///etc/passwd`` — hostname пустой, прежняя проверка его пропускала;
* ``data:text/html,...``, ``chrome://settings`` — не-HTTP схемы;
* ``http://2130706433/`` — десятичная запись ``127.0.0.1``;
* ``http://0x7f000001/`` — шестнадцатеричная запись loopback;
* ``http://127.1/`` — сокращённая запись ``127.0.0.1``;
* ``http://[::ffff:127.0.0.1]/`` — IPv4-mapped IPv6.

Контракт — **fail-closed**: любое несоответствие вызывает
:class:`UrlNotAllowedError`. Обойти проверку нельзя «по-тихому»: функция
возвращает нормализованный URL либо бросает исключение.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

__all__ = (
    "ALLOWED_URL_SCHEMES",
    "UrlNotAllowedError",
    "assert_safe_url",
    "is_safe_url",
)

#: Разрешённые схемы. ``file:``, ``data:``, ``javascript:``, ``chrome:``,
#: ``about:`` и прочие не проходят: браузер умеет их открыть, значит
#: злоумышленник сможет через них и добраться.
ALLOWED_URL_SCHEMES = frozenset({"http", "https"})

#: Хосты облачных метаданных и локальные псевдонимы. Проверяются и по
#: имени, и по IP — имя может резолвиться куда угодно.
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "metadata.aws",
        "instance-data",
    }
)


class UrlNotAllowedError(ValueError):
    """URL не проходит SSRF-политику.

    Наследует :class:`ValueError` ради обратной совместимости с
    ``scraping.py``, который ловит именно ``ValueError``.
    """


def _strip_brackets(host: str) -> str:
    """Убрать квадратные скобки IPv6-литерала.

    Args:
        host: Хост как вернул ``urlsplit``.

    Returns:
        Хост без скобок.

    """
    if host.startswith("[") and host.endswith("]"):
        return host[1:-1]
    return host


def _numeric_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Разобрать нестандартные числовые записи IP-адреса.

    ``ipaddress.ip_address`` понимает только пунктирную запись, поэтому
    ``http://2130706433/`` (десятичная форма ``127.0.0.1``) и
    ``http://0x7f000001/`` (шестнадцатеричная) проходили мимо проверки.

    Args:
        host: Проверяемый хост.

    Returns:
        Адрес, если хост является числовой записью IP, иначе ``None``.

    """
    if not host:
        return None
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass

    stripped = host.lower()

    # Шестнадцатеричная: 0x7f000001
    if stripped.startswith("0x"):
        try:
            value = int(stripped, 16)
        except ValueError:
            return None
        if value > 0xFFFFFFFF:
            return None
        return ipaddress.IPv4Address(value)

    # Восьмеричная: 017700000001 — Chromium читает ведущий ноль как octal.
    if len(stripped) > 1 and stripped.startswith("0") and stripped.isdigit():
        try:
            value = int(stripped, 8)
        except ValueError:
            return None
        if value > 0xFFFFFFFF:
            return None
        return ipaddress.IPv4Address(value)

    # Десятичная целиком: 2130706433 == 127.0.0.1
    if stripped.isdigit():
        value = int(stripped, 10)
        if value > 0xFFFFFFFF:
            return None
        return ipaddress.IPv4Address(value)

    # Сокращённая пунктирная запись. Семантика Chromium: первая часть —
    # старший байт, последняя заполняет оставшиеся младшие байты, а НЕ
    # дописывает нули справа. То есть ``127.1`` — это 127.0.0.1, а не
    # 127.1.0.0. Ошибка здесь незаметна: обе формы приватные, но
    # сообщение об отказе врало бы о развёрнутом адресе.
    parts = stripped.split(".")
    if 1 < len(parts) <= 4 and all(part.isdigit() for part in parts):
        numbers = [int(part) for part in parts]
        if any(value > 255 for value in numbers[:-1]):
            return None
        last = numbers[-1]
        remaining = 4 - (len(numbers) - 1)
        if last >= 256**remaining:
            return None
        packed: list[int] = numbers[:-1]
        for shift in range(remaining - 1, -1, -1):
            packed.append((last >> (8 * shift)) & 0xFF)
        value_int = 0
        for octet in packed:
            value_int = (value_int << 8) | octet
        return ipaddress.IPv4Address(value_int)

    return None


def _is_forbidden_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> str | None:
    """Определить, запрещён ли адрес.

    Args:
        address: Разобранный IP-адрес.

    Returns:
        Причина запрета либо ``None``, если адрес допустим.

    """
    if isinstance(address, ipaddress.IPv6Address):
        # IPv4-mapped/teredo адреса обходят обычные проверки, поэтому
        # снимаем маску и смотрим на вложенный IPv4.
        if address.ipv4_mapped is not None:
            return _is_forbidden_address(address.ipv4_mapped)
        if address.sixtofour is not None:
            return _is_forbidden_address(address.sixtofour)

    checks = (
        ("loopback", address.is_loopback),
        ("private", address.is_private),
        ("link-local", address.is_link_local),
        ("unspecified", address.is_unspecified),
        ("multicast", address.is_multicast),
        ("reserved", address.is_reserved),
    )
    for label, matched in checks:
        if matched:
            return label
    return None


def assert_safe_url(
    url: str,
    *,
    allow_private: bool = False,
    allow_hosts: frozenset[str] | set[str] | None = None,
) -> str:
    """Проверить URL по SSRF-политике или бросить исключение.

    Args:
        url: Проверяемый URL.
        allow_private: Разрешить приватные/loopback-адреса. По умолчанию
            ``False`` — fail-closed. Включать только для осознанного
            локального обхода браузера.
        allow_hosts: Явный белый список хостов. Если задан, любой хост вне
            списка отклоняется.

    Returns:
        Нормализованный URL (схема в нижнем регистре).

    Raises:
        UrlNotAllowedError: схема не разрешена, хост пуст, хост или адрес
            запрещены политикой.

    """
    if not isinstance(url, str) or not url.strip():
        raise UrlNotAllowedError("URL пуст")

    candidate = url.strip()
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        raise UrlNotAllowedError(f"URL не разбирается: {exc}") from exc

    scheme = (parts.scheme or "").lower()
    if not scheme:
        raise UrlNotAllowedError(f"У URL нет схемы: {url!r}")
    if scheme not in ALLOWED_URL_SCHEMES:
        raise UrlNotAllowedError(
            f"Схема {scheme!r} не разрешена; допустимы только "
            f"{', '.join(sorted(ALLOWED_URL_SCHEMES))}"
        )

    host = _strip_brackets((parts.hostname or "").lower())
    if not host:
        raise UrlNotAllowedError(f"У URL нет хоста: {url!r}")

    if allow_hosts is not None and host not in {item.lower() for item in allow_hosts}:
        raise UrlNotAllowedError(f"Хост {host!r} отсутствует в allow_hosts")

    if host in _BLOCKED_HOSTS:
        raise UrlNotAllowedError(f"Хост {host!r} заблокирован политикой")

    address = _numeric_ip(host)
    if address is not None:
        if not allow_private:
            reason = _is_forbidden_address(address)
            if reason is not None:
                raise UrlNotAllowedError(
                    f"Адрес {host!r} запрещён ({reason}): {address}"
                )
    elif allow_private is False and "." not in host and ":" not in host:
        # Одиночное имя без точки может резолвиться во внутреннюю сеть
        # через корпоративный DNS — по умолчанию не доверяем.
        raise UrlNotAllowedError(
            f"Хост {host!r} не является FQDN или IP — внутреннее имя, отклонено"
        )

    return candidate


def is_safe_url(
    url: str,
    *,
    allow_private: bool = False,
    allow_hosts: frozenset[str] | set[str] | None = None,
) -> bool:
    """Проверить URL без исключений.

    Args:
        url: Проверяемый URL.
        allow_private: Разрешить приватные адреса.
        allow_hosts: Белый список хостов.

    Returns:
        ``True``, если URL проходит политику.

    """
    try:
        assert_safe_url(url, allow_private=allow_private, allow_hosts=allow_hosts)
    except UrlNotAllowedError:
        return False
    return True
