"""F-AP1: SSRF-guard обязан отбивать не-HTTP схемы и нестандартные IP.

Каждый payload из этого списка **реально доходил до браузера** до фикса
(F-AP1, CRITICAL). Тест фиксирует контракт ``core.net.url_guard`` и является
регрессией для 11 точек ``page.goto``, которые теперь обязаны звать guard.
"""

from __future__ import annotations

import pytest

from src.backend.core.net.url_guard import (
    ALLOWED_URL_SCHEMES,
    UrlNotAllowedError,
    assert_safe_url,
    is_safe_url,
)

#: Payload'ы, каждый из которых до фикса дошёл до ``page.goto``.
BLOCKED_PAYLOADS: tuple[tuple[str, str], ...] = (
    ("file-local-read", "file:///etc/passwd"),
    ("file-encoded", "file://%2Fetc%2Fpasswd"),
    ("data-html", "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="),
    ("chrome-scheme", "chrome://settings"),
    ("about-scheme", "about:blank"),
    ("javascript-scheme", "javascript:alert(1)"),
    ("metadata-link-local", "http://169.254.169.254/latest/meta-data/"),
    ("loopback-decimal", "http://2130706433/"),
    ("loopback-hex", "http://0x7f000001/"),
    ("loopback-short", "http://127.1/"),
    ("ipv4-mapped-ipv6", "http://[::ffff:127.0.0.1]/"),
    ("private-10", "http://10.0.0.1/"),
    ("private-192-168", "http://192.168.1.1/"),
    ("localhost-name", "http://localhost:8080/admin"),
    ("metadata-aws", "http://metadata.aws/"),
    ("no-scheme", "//evil.example.com/x"),
    ("empty", ""),
    ("scheme-only", "https://"),
)

#: Легитимные URL — guard не должен ломать рабочую навигацию.
ALLOWED_URLS: tuple[str, ...] = (
    "https://example.com/",
    "http://example.org/path?q=1",
    "https://sub.domain.example.co.uk/a/b#frag",
    "https://8.8.8.8/",
    "https://[2606:4700:4700::1111]/",
)


class TestSchemesAreAllowlisted:
    """Только http/https — браузер умеет иное, злоумышленник тоже."""

    def test_allowed_schemes_are_exactly_http_https(self) -> None:
        """Контракт схем зафиксирован: расширять список нельзя молча."""
        assert ALLOWED_URL_SCHEMES == frozenset({"http", "https"})

    @pytest.mark.parametrize(("name", "url"), BLOCKED_PAYLOADS)
    def test_payload_is_rejected(self, name: str, url: str) -> None:
        """Каждый исторический payload отбивается.

        Args:
            name: Имя payload'а (для читаемости отчёта).
            url: Проверяемый URL.

        """
        assert not is_safe_url(url), f"{name}: {url!r} не отбит"

    @pytest.mark.parametrize("url", ALLOWED_URLS)
    def test_legitimate_url_passes(self, url: str) -> None:
        """Рабочая навигация не ломается.

        Args:
            url: Легитимный URL.

        """
        assert is_safe_url(url), f"{url!r} ошибочно отбит"

    def test_returns_normalized_url(self) -> None:
        """Возвращается сам URL, чтобы вызывающий не терял контекст."""
        assert assert_safe_url("  https://example.com/x  ") == "https://example.com/x"


class TestFailClosed:
    """Исключение, а не тихий возврат: вызывающий обязан остановиться."""

    def test_raises_url_not_allowed(self) -> None:
        """Отклонённый URL обязан бросать исключение."""
        with pytest.raises(UrlNotAllowedError):
            assert_safe_url("file:///etc/passwd")

    def test_error_is_value_error_subclass(self) -> None:
        """Наследует ValueError — обратная совместимость с scraping.py."""
        assert issubclass(UrlNotAllowedError, ValueError)

    @pytest.mark.parametrize(("name", "url"), BLOCKED_PAYLOADS)
    def test_reason_is_reported(self, name: str, url: str) -> None:
        """Сообщение объясняет причину, а не молчит.

        Args:
            name: Имя payload'а.
            url: Проверяемый URL.

        """
        with pytest.raises(UrlNotAllowedError) as exc:
            assert_safe_url(url)
        assert str(exc.value).strip(), f"{name}: пустое сообщение об отказе"


class TestKnownResidualRiskDnsRebinding:
    """DNS-алиас на loopback валидатором строки не отбивается — и это не
    исправляется здесь намеренно.

    ``http://127.0.0.1.nip.io/`` — валидное FQDN, которое резолвится в
    ``127.0.0.1``. Чтобы отбить такое, нужно резолвить DNS. Но браузер
    резолвит **сам**, повторно и уже после нашей проверки, поэтому
    pre-resolve даёт TOCTOU-окно и не защищает от DNS rebinding: ответ может
    различаться между нашей проверкой и фактическим соединением.

    Единственная честная защита — заставлять браузер идти через
    фиксированный резолвер или прокси, который резолвит один раз и
    подставляет IP. Это отдельное архитектурное решение (ADR), а не правка
    валидатора. Блоклинг по списку ``*.nip.io`` был бы имитацией защиты:
    список бесконечен, обходится через любой другой DNS-алиас.
    """

    def test_dns_alias_is_a_known_gap_not_a_silent_pass(self) -> None:
        """Документирует gap и требует, чтобы он остался видимым."""
        assert is_safe_url("http://127.0.0.1.nip.io/"), (
            "ожидаем, что guard отбивает только литеральные адреса; "
            "если этот тест стал красным — значит поведение изменилось "
            "и остаточный риск нужно пересмотреть заново"
        )


class TestExplicitOptIn:
    """Локальный обход браузера возможен, но только явным флагом."""

    def test_private_blocked_by_default(self) -> None:
        """По умолчанию приватные адреса запрещены (fail-closed)."""
        assert not is_safe_url("http://127.0.0.1:8080/")

    def test_allow_private_opens_localhost(self) -> None:
        """Явный opt-in открывает loopback — для осознанного локального RPA."""
        assert is_safe_url("http://127.0.0.1:8080/", allow_private=True)

    def test_allow_private_still_rejects_other_scheme(self) -> None:
        """``allow_private`` не отключает проверку схемы."""
        assert not is_safe_url("file:///etc/passwd", allow_private=True)

    def test_allow_private_still_rejects_metadata_name(self) -> None:
        """Имя хоста проверяется всегда, независимо от флага."""
        assert not is_safe_url("http://metadata.aws/", allow_private=True)

    def test_allow_hosts_whitelist(self) -> None:
        """Явный белый список хостов сужает политику."""
        allowed = frozenset({"example.com"})
        assert is_safe_url("https://example.com/x", allow_hosts=allowed)
        assert not is_safe_url("https://other.com/x", allow_hosts=allowed)

    def test_allow_hosts_ignores_case(self) -> None:
        """Регистр хоста не должен обходить белый список."""
        assert is_safe_url(
            "https://EXAMPLE.com/x", allow_hosts=frozenset({"example.com"})
        )


class TestExoticIpEncodings:
    """Chromium понимает больше числовых форм, чем ``ipaddress``."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("http://2130706433/", "127.0.0.1"),  # десятичная
            ("http://0x7f000001/", "127.0.0.1"),  # шестнадцатеричная
            ("http://017700000001/", "127.0.0.1"),  # восьмеричная
            ("http://127.1/", "127.0.0.1"),  # сокращённая
            ("http://[::ffff:127.0.0.1]/", "127.0.0.1"),  # IPv4-mapped
        ],
    )
    def test_loopback_encodings_blocked(self, url: str, expected: str) -> None:
        """Все формы записи loopback отбиваются **именно как адреса**.

        Проверяется не только факт отказа, но и его причина: сообщение
        обязано называть развёрнутый адрес. Без этого тест проходил бы и
        при сломанном разборе нестандартных записей — хост просто
        отбивался бы как «не FQDN», и регрессия осталась бы незамеченной.

        Args:
            url: Проверяемый URL.
            expected: Адрес, который обязан появиться в причине отказа.

        """
        assert not is_safe_url(url), f"{url!r} не отбит"
        with pytest.raises(UrlNotAllowedError) as exc:
            assert_safe_url(url)
        message = str(exc.value)
        assert expected in message, (
            f"{url!r}: отказ должен называть развёрнутый адрес {expected}, "
            f"а не отбивать хост по другой причине: {message!r}"
        )

    def test_numeric_host_rejected_as_address_not_as_name(self) -> None:
        """Чисто числовой хост обязан диагностироваться как адрес.

        Без отдельной проверки этот случай отбивался бы «не FQDN» —
        то есть тест проходил бы при мёртвом разборе числовых форм.
        """
        with pytest.raises(UrlNotAllowedError) as exc:
            assert_safe_url("http://2130706433/")
        assert "127.0.0.1" in str(exc.value)


class TestDottedMixedRadixBypass:
    """Регрессия: пунктирные hex/octal-формы и FQDN с корневой точкой.

    Adversarial review нашёл три обхода, которые guard пропускал, хотя
    каждая резолвится в 127.0.0.1 системным резолвером и в Chromium:
    ``0x7f.0.0.1``, ``0177.0.0.1`` и ``localhost.``. Прежний разбор
    понимал только ЦЕЛОЧИСЛЕННЫЕ формы того же адреса, а хост сравнивался
    с _BLOCKED_HOSTS без нормализации на точку.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "http://0x7f.0.0.1/",
            "http://0177.0.0.1/",
            "http://0x7f.1/",
            "http://0177.1/",
            "http://0x7f000001/",
            "http://017700000001/",
            "http://127.1/",
            "http://127.0.1/",
        ],
    )
    def test_dotted_mixed_radix_loopback_is_blocked(self, url: str) -> None:
        """Пунктирные dec/octal/hex записи 127.0.0.1 должны блокироваться."""
        with pytest.raises(UrlNotAllowedError):
            assert_safe_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost./",
            "http://LOCALHOST./",
            "http://localhost..",
            "http://ip6-localhost./",
        ],
    )
    def test_trailing_dot_localhost_is_blocked(self, url: str) -> None:
        """«localhost.» — тот же loopback; корневая точка не обходит политику."""
        with pytest.raises(UrlNotAllowedError):
            assert_safe_url(url)

    @pytest.mark.parametrize(
        "url", ["http://example.com/", "https://sub.example.org/p"]
    )
    def test_public_hosts_still_allowed(self, url: str) -> None:
        """Нормализация не должна сломать легитимные публичные адреса."""
        assert assert_safe_url(url) is not None


class TestCgnatAndRoutability:
    """B-4 (adversarial review): shared address space 100.64.0.0/10.

    В Python 3.14 для CGNAT ``is_private`` == False и ``is_reserved`` ==
    False, поэтому адреса проходили guard, хотя в cloud/k8s это штатный
    внутренний диапазон. Ловится явно, а не через ``is_private``.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "http://100.64.0.1/",
            "http://100.64.1.1/",
            "http://100.127.255.255/",
            "https://100.100.100.100/",
        ],
    )
    def test_cgnat_is_blocked(self, url: str) -> None:
        """Shared address space не должен достигать браузера."""
        with pytest.raises(UrlNotAllowedError):
            assert_safe_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://100.63.255.255/",  # до границы /10
            "http://100.128.0.1/",  # после границы /10
            "http://8.8.8.8/",
        ],
    )
    def test_neighbours_of_cgnat_still_allowed(self, url: str) -> None:
        """Границы диапазона не должны блокироваться сверх необходимого."""
        assert assert_safe_url(url) is not None


class TestNotGloballyRoutable:
    """Fail-closed хвост: не-глобально-маршрутизируемое не пропускаем."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://192.0.2.1/",  # TEST-NET-1
            "http://198.51.100.1/",  # TEST-NET-2
            "http://203.0.113.1/",  # TEST-NET-3
        ],
    )
    def test_documentation_ranges_blocked(self, url: str) -> None:
        """Документационные диапазоны не маршрутизируются в интернет."""
        with pytest.raises(UrlNotAllowedError):
            assert_safe_url(url)


class TestIpv6NotGloballyRoutable:
    """Fail-closed для IPv6: шестьtov4 (6to4) и не-reject-to-globally-routable.

    B-4 follow-up (adversarial review): IPv6-обходные пути (``ipv4_mapped``,
    ``sixtofour``) требовали явной рекурсивной проверки; ``is_global`` False
    должен срабатывать как fail-closed хвост для будущих диапазонов.
    """

    @pytest.mark.parametrize(
        "url",
        [
            # 6to4: 2002::/16 → IPv4 в нижних 32 битах
            "http://[2002:7f00:0001::]/",
            "http://[2002:0a00:0001::]/",
            # IPv4-mapped IPv6 — guard должен рекурсивно отклонить
            "http://[::ffff:127.0.0.1]/",
            "http://[::ffff:10.0.0.1]/",
            # Link-local IPv6
            "http://[fe80::1]/",
            # Multicast IPv6
            "http://[ff02::1]/",
        ],
    )
    def test_ipv6_forbidden(self, url: str) -> None:
        """Любой непрямой IPv6-адрес обязан проходить _is_forbidden_address."""
        with pytest.raises(UrlNotAllowedError):
            assert_safe_url(url)


class TestMixedRadixDottedIp:
    """B-4 (follow-up): dotted IPv4 с разными системами счисления.

    Chromium читает ``0x7f.0.0.1`` как ``127.0.0.1``. ``ipaddress.IPv4Address``
    не разбирает такие формы; guard делает это вручную и должен их
    отклонить, если результат приватный.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "http://0x7f.0.0.1/",  # hex first octet
            "http://127.0.0x0.1/",  # hex middle octet
            "http://0177.0.0.1/",  # octal first octet
            "http://127.0.0177.1/",  # octal in dotted — Chromium resolves
            "http://0xff.0.0.1/",  # hex > 0x7f → not loopback, but is_private
        ],
    )
    def test_dotted_mixed_radix_blocked(self, url: str) -> None:
        """Смешанные системы счисления в пунктирной IPv4-форме блокируются."""
        with pytest.raises(UrlNotAllowedError):
            assert_safe_url(url)


class TestNonGloballyRoutableTail:
    """``is_global=False`` — fail-closed хвост для неизвестных/reserved
    диапазонов, которые stdlib может не считать reserved явно.
    """

    @pytest.mark.parametrize(
        "url",
        [
            # TEST-NET-1/2/3 (RFC 5737) — is_global=False в Python 3.14
            "http://192.0.2.1/",
            "http://198.51.100.1/",
            "http://203.0.113.1/",
            # Reserved/future use
            "http://240.0.0.1/",
            "http://255.255.255.255/",
        ],
    )
    def test_non_globally_routable_blocked(self, url: str) -> None:
        """is_global=False должен попадать в fail-closed хвост."""
        with pytest.raises(UrlNotAllowedError):
            assert_safe_url(url)
