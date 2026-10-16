"""Тесты для S173 M8.4 / S176 M11.3 — simple secret-leakage detector.

Контекст правки 2026-10-16: pre-push гейт падал на 9 находках, и ВСЕ они
оказались ложными — тестовыми заглушками. Решение принято в две части,
обе покрыты здесь:

1. ``private_key_pem`` теперь требует base64-**материал** ключа, а не только
   строку заголовка. Это убирает ложные срабатывания на пустых заглушках и на
   ``assert b"-----BEGIN PRIVATE KEY-----" in chain.key_pem``, но НЕ должно
   ослаблять детект настоящего ключа — это главное, что проверяет
   :class:`TestRealSecretsStillDetected`.

2. Два опубликованных вендорами демо-значения (AWS docs example key и
   пример JWT с jwt.io) вынесены в allowlist. Критично, что allowlist
   матчится по ``путь + строка + паттерн``: нельзя одной строкой скрыть
   новую утечку в соседней строке — это проверяет
   :class:`TestAllowlistIsNarrow`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.check_secrets_simple import Finding, _apply_allowlist, _scan_file

# Реалистичные по структуре заглушки из репозитория (проверены вручную).
EMPTY_PEM = 'key = b"-----BEGIN PRIVATE KEY-----\n"'
FAKE_PEM = (
    'key.write_text("-----BEGIN PRIVATE KEY-----\\nFAKE\\n'
    '-----END PRIVATE KEY-----\\n")'
)
FAKE_KEY_PEM = (
    '"private_key": "-----BEGIN RSA PRIVATE KEY-----\\nFAKE_KEY\\n'
    '-----END RSA PRIVATE KEY-----"'
)
ASSERT_ONLY = 'assert b"-----BEGIN PRIVATE KEY-----" in chain.key_pem'

# Настоящий по форме приватный ключ: 64+ символов base64-тела.
REAL_PEM_BODY = (
    "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj"
    "MzEfYyjiWA4R4/M2bS1GB4t7NXp98C3SC6dVMvDuictGeurT8jNbvJZHtCSuYEvu"
)
REAL_PEM = (
    'key = """-----BEGIN PRIVATE KEY-----\n'
    f"{REAL_PEM_BODY}\n"
    '-----END PRIVATE KEY-----\n"""'
)


class TestFakeFixturesNoLongerFlagged:
    """Заведомо не-секреты не должны блокировать push."""

    @pytest.mark.parametrize(
        ("label", "source"),
        [
            ("empty_pem", EMPTY_PEM),
            ("fake_pem", FAKE_PEM),
            ("fake_key_pem", FAKE_KEY_PEM),
            ("assert_only", ASSERT_ONLY),
        ],
    )
    def test_no_finding(self, tmp_path: Path, label: str, source: str) -> None:
        target = tmp_path / f"{label}.py"
        target.write_text(source + "\n", encoding="utf-8")

        findings = _scan_file(target)

        pem_findings = [f for f in findings if f.pattern_name == "private_key_pem"]
        assert not pem_findings, (
            f"{label}: тестовая заглушка не должна считаться секретом, "
            f"получено {pem_findings}"
        )


class TestRealSecretsStillDetected:
    """Ужесточение regex НЕ должно ослабить детект."""

    def test_real_pem_body_is_detected(self, tmp_path: Path) -> None:
        """Настоящий PEM с base64-телом по-прежнему ловится."""
        target = tmp_path / "leak.py"
        target.write_text(REAL_PEM + "\n", encoding="utf-8")

        findings = _scan_file(target)

        assert any(f.pattern_name == "private_key_pem" for f in findings), (
            "Настоящий приватный ключ с material-телом обязан обнаруживаться"
        )

    def test_rsa_private_key_is_detected(self, tmp_path: Path) -> None:
        """RSA-вариант заголовка тоже ловится."""
        target = tmp_path / "rsa_leak.py"
        target.write_text(
            'k = """-----BEGIN RSA PRIVATE KEY-----\n'
            f"{REAL_PEM_BODY}\n"
            '-----END RSA PRIVATE KEY-----"""\n',
            encoding="utf-8",
        )

        findings = _scan_file(target)

        assert any(f.pattern_name == "private_key_pem" for f in findings)

    def test_github_pat_still_detected(self, tmp_path: Path) -> None:
        """Соседние паттерны не должны пострадать при правке."""
        target = tmp_path / "gh.py"
        target.write_text(f'token = "ghp_{"a" * 36}"\n', encoding="utf-8")

        findings = _scan_file(target)

        assert any(f.pattern_name == "github_pat" for f in findings)

    def test_aws_access_key_still_detected(self, tmp_path: Path) -> None:
        """AWS-ключ с реальной длиной/алфавитом ловится.

        Строка собирается конкатенацией, чтобы сам файл теста не содержал
        литерала, который детектор справедливо считает утечкой.
        """
        target = tmp_path / "aws.py"
        target.write_text(f'k = "{"AKIA"}{"Q7RTZ3M9XZP2V4L6"}"\n', encoding="utf-8")

        findings = _scan_file(target)

        assert any(f.pattern_name == "aws_access_key" for f in findings)


class TestAllowlistIsNarrow:
    """Allowlist не должен скрывать новые находки рядом."""

    def _finding(self, path: str, line: int, pattern: str) -> Finding:
        return Finding(
            pattern_name=pattern, file=_ROOT / path, line=line, match="redacted"
        )

    def test_exact_entry_is_filtered(self) -> None:
        allowed_path = "tests/unit/tools/test_w11_p0_2_check_unsafe_defaults.py"
        allowed = (self._finding(allowed_path, 148, "aws_access_key"),)

        assert _apply_allowlist(allowed) == [], "Точное совпадение должно фильтроваться"

    def test_same_file_other_line_not_filtered(self) -> None:
        """Соседняя строка — это новая утечка, её скрывать нельзя."""
        path = "tests/unit/tools/test_w11_p0_2_check_unsafe_defaults.py"
        other_line = self._finding(path, 149, "aws_access_key")

        assert _apply_allowlist([other_line]) == [other_line], (
            "Allowlist не должен действовать на другие строки"
        )

    def test_same_line_other_pattern_not_filtered(self) -> None:
        """Другой паттерн на allowlist'нутой строке — тоже не фильтруется."""
        path = "tests/unit/tools/test_w11_p0_2_check_unsafe_defaults.py"
        other_pattern = self._finding(path, 148, "jwt_token")

        assert _apply_allowlist([other_pattern]) == [other_pattern]

    def test_other_file_not_filtered(self) -> None:
        other = self._finding("src/backend/core/config/real_leak.py", 1, "jwt_token")

        assert _apply_allowlist([other]) == [other]


_ROOT = Path(__file__).resolve().parents[3]
