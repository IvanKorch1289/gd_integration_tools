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
# Shared address space (RFC 6598) — внутренний диапазон в cloud/k8s.
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")

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


def _dotted_numeric_ip(host: str) -> ipaddress.IPv4Address | None:
    """Разобрать пунктирный IPv4, где каждая часть может быть dec/octal/hex.

    Браузеры (и POSIX-резолверы) трактуют каждую часть отдельно: ``0x7f``
    читается как hex 127, ``0177`` — как octal 127. Поэтому
    ``http://0x7f.0.0.1/`` и ``http://0177.0.0.1/`` ведут в loopback,
    хотя ``ipaddress.ip_address`` такие формы отвергает.

    Args:
        host: Проверяемый хост в нижнем регистре.

    Returns:
        Адрес, если хост распознан как пунктирный IPv4, иначе ``None``.

    """
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    octets: list[int] = []
    for part in parts:
        try:
            if part.startswith("0x"):
                value = int(part, 16)
            elif len(part) > 1 and part.startswith("0"):
                value = int(part, 8)
            else:
                value = int(part, 10)
        except ValueError:
            return None
        octets.append(value)
    # Семантика inet_aton: все части, кроме последней, занимают по одному
    # байту; последняя добирает оставшиеся.
    #   1 часть -> [32]   2 -> [8,24]   3 -> [8,8,16]   4 -> [8,8,8,8]
    count = len(octets)
    value = 0
    for index, octet in enumerate(octets):
        if index < count - 1:
            width = 8
        else:
            width = 8 * (5 - count)
        if octet >= 1 << width:
            return None
        value = (value << width) | octet
    return ipaddress.IPv4Address(value)


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

    # Пунктирная запись, где каждая часть может быть dec/octal/hex:
    # ``0x7f.0.0.1`` и ``0177.0.0.1`` Chromium резолвит в 127.0.0.1, хотя
    # целочисленные формы того же адреса разбираются ниже. Без этой ветки
    # guard отвечал ALLOWED на оба варианта.
    dotted = _dotted_numeric_ip(stripped)
    if dotted is not None:
        return dotted

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

    # B-4 (adversarial review): shared address space 100.64.0.0/10.
    # В Python 3.14 для него is_private == False и is_reserved == False,
    # поэтому CGNAT-адреса проходили guard, хотя в cloud/k8s это штатный
    # внутренний диапазон. Ловим явно, а не через is_private.
    if isinstance(address, ipaddress.IPv4Address) and address in _CGNAT_NETWORK:
        return "shared/CGNAT"

    # Fail-closed хвост: адрес, который не является глобально маршрутизируемым,
    # не должен достигать браузера. Это покрывает и будущие нестандартные
    # диапазоны, которые stdlib может не считать reserved.
    if not address.is_global:
        return "not-globally-routable"
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
    # Нормализация FQDN: «localhost.» и «LOCALHOST.» резолвятся в loopback
    # так же, как «localhost», а точное сравнение с _BLOCKED_HOSTS их
    # пропускало. Хост используется только для проверок — сам URL candidate
    # не меняется, поэтому внешний вид адреса сохраняется.
    host = host.rstrip(".")
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
