"""TDD: tools/config_audit.py — гейт рассинхронизации YAML и моделей (Wave 13 Q16).

Класс дефекта
-------------
Механизм загрузки конфигурации ТИХО отбрасывает неизвестные YAML-ключи
(``FilteredSettingsSource._filter_data``): опечатка в имени = тихая потеря
настройки. Инструмент ``tools/config_audit.py`` умеет находить такие
расхождения, но раньше не был подключён к CI и не покрыт тестами.

Два класса расхождений
----------------------
* **orphan-класс** (``orphan-group`` / ``orphan-key``) — наш дефект:
  YAML-ключ без поля в модели = опечатка = тихая потеря настройки.
  Блокирующий scope гейта (по умолчанию ``--scope orphans``).
* **missing-класс** (``missing-secret`` / ``missing-non-secret``) — другой
  дефект (переменные окружения не документированы в ``.env.example``),
  отдельная owner-задача. Показывается отдельной неблокирующей секцией.

Контракт гейта:
* известный долг живёт в ``tools/config_audit_allowlist.txt``;
* гейт падает только на НОВЫХ orphan-расхождениях (exit 1);
* чистое состояние — exit 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.config_audit import main

PROFILES: tuple[str, ...] = ("dev", "dev_light", "staging", "prod")

_SETTINGS_SOURCE = '''
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class DemoSettings(BaseSettings):
    """Demo-настройки для тестов аудита."""

    yaml_group: ClassVar[str | None] = "demo"
    model_config = SettingsConfigDict(env_prefix="DEMO_", extra="forbid")

    known_field: int = 1
'''

_SECRET_CLASS = '''

class SecretSettings(BaseSettings):
    """Секретные demo-настройки."""

    yaml_group: ClassVar[str | None] = "secret_demo"
    model_config = SettingsConfigDict(env_prefix="SECRET_", extra="forbid")

    api_key: str
'''

_REQUIRED_CLASS = '''

class RequiredSettings(BaseSettings):
    """Demo-настройки с обязательным полем."""

    yaml_group: ClassVar[str | None] = "required_demo"
    model_config = SettingsConfigDict(env_prefix="REQ_", extra="forbid")

    endpoint: str
'''


@pytest.fixture
def demo_repo(tmp_path: Path) -> Path:
    """Мини-репозиторий: каталог моделей + каталог профилей."""
    (tmp_path / "config").mkdir()
    (tmp_path / "profiles").mkdir()
    (tmp_path / ".env.example").write_text("", encoding="utf-8")
    return tmp_path


def _write_settings(repo: Path, body: str = _SETTINGS_SOURCE) -> None:
    """Записывает модуль с Settings-классом в demo-репозиторий."""
    (repo / "config" / "demo_settings.py").write_text(body, encoding="utf-8")


def _write_profile(repo: Path, profile: str, body: str) -> None:
    """Записывает YAML-overlay профиля в demo-репозиторий."""
    (repo / "profiles" / f"{profile}.yml").write_text(body, encoding="utf-8")


def _run(repo: Path, *extra: str) -> int:
    """Запускает гейт на demo-репозитории."""
    return main(
        [
            "--config-dir",
            str(repo / "config"),
            "--profiles-dir",
            str(repo / "profiles"),
            "--env-example",
            str(repo / ".env.example"),
            "--allowlist",
            str(repo / "allowlist.txt"),
            *extra,
        ]
    )


class TestConfigAuditFindings:
    """Поиск расхождений YAML ↔ модель настроек."""

    def test_clean_profile_has_no_issues(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Синхронный конфиг → exit 0 и «OK: 0 orphan issues»."""
        _write_settings(demo_repo)
        _write_profile(demo_repo, "dev", "demo:\n  known_field: 1\n")

        assert _run(demo_repo, "--profile", "dev") == 0
        assert "OK: 0 orphan issues" in capsys.readouterr().out

    def test_orphan_group_is_detected(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Секция YAML без соответствующего Settings-класса → нарушение."""
        _write_settings(demo_repo)
        _write_profile(
            demo_repo, "dev", "demo:\n  known_field: 1\nunknown_section:\n  x: 1\n"
        )

        assert _run(demo_repo, "--profile", "dev") == 1
        out = capsys.readouterr().out
        assert "ORPHAN-GROUP" in out
        assert "unknown_section" in out

    def test_orphan_key_is_detected(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Ключ в секции без поля в ``model_fields`` → нарушение."""
        _write_settings(demo_repo)
        _write_profile(demo_repo, "dev", "demo:\n  known_field: 1\n  typo_field: 2\n")

        assert _run(demo_repo, "--profile", "dev") == 1
        out = capsys.readouterr().out
        assert "[orphan]" in out
        assert "typo_field" in out

    def test_missing_secret_is_not_blocking_by_default(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """missing-secret — отдельный класс дефекта: виден, но не блокирует."""
        _write_settings(demo_repo, _SETTINGS_SOURCE + _SECRET_CLASS)
        _write_profile(demo_repo, "dev", "secret_demo:\n  api_key: x\n")

        assert _run(demo_repo, "--profile", "dev") == 0
        out = capsys.readouterr().out
        assert "NON-BLOCKING" in out
        assert "SECRET_API_KEY" in out

    def test_scope_all_blocks_on_missing_secret(self, demo_repo: Path) -> None:
        """``--scope all`` расширяет блокирующий scope на missing-класс."""
        _write_settings(demo_repo, _SETTINGS_SOURCE + _SECRET_CLASS)
        _write_profile(demo_repo, "dev", "secret_demo:\n  api_key: x\n")

        assert _run(demo_repo, "--profile", "dev", "--scope", "all") == 1

    def test_missing_non_secret_is_not_blocking_by_default(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """missing-non-secret — отдельный класс дефекта: виден, но не блокирует."""
        _write_settings(demo_repo, _SETTINGS_SOURCE + _REQUIRED_CLASS)
        _write_profile(demo_repo, "dev", "required_demo: {}\n")

        assert _run(demo_repo, "--profile", "dev") == 0
        out = capsys.readouterr().out
        assert "NON-BLOCKING" in out
        assert "endpoint" in out


class TestConfigAuditGate:
    """Exit codes, allowlist и режимы запуска гейта."""

    def test_allowlisted_issue_is_not_a_new_violation(self, demo_repo: Path) -> None:
        """Известный долг в allowlist → гейт зелёный."""
        _write_settings(demo_repo)
        _write_profile(demo_repo, "dev", "demo:\n  known_field: 1\n  typo_field: 2\n")
        (demo_repo / "allowlist.txt").write_text(
            "orphan-key:dev:demo:typo_field  # owner=core | reason=baseline\n",
            encoding="utf-8",
        )

        assert _run(demo_repo, "--profile", "dev") == 0

    def test_new_issue_fails_even_with_allowlist(self, demo_repo: Path) -> None:
        """Новый orphan-ключ → exit 1, несмотря на baseline."""
        _write_settings(demo_repo)
        _write_profile(demo_repo, "dev", "demo:\n  known_field: 1\n  typo_field: 2\n")
        (demo_repo / "allowlist.txt").write_text(
            "orphan-key:dev:demo:other_key  # owner=core | reason=baseline\n",
            encoding="utf-8",
        )

        assert _run(demo_repo, "--profile", "dev") == 1

    def test_update_allowlist_writes_baseline(self, demo_repo: Path) -> None:
        """``--update-allowlist`` фиксирует текущий долг в baseline."""
        _write_settings(demo_repo)
        _write_profile(demo_repo, "dev", "demo:\n  known_field: 1\n  typo_field: 2\n")

        assert _run(demo_repo, "--profile", "dev", "--update-allowlist") == 0
        allowlist = (demo_repo / "allowlist.txt").read_text(encoding="utf-8")
        assert "orphan-key:dev:demo:typo_field" in allowlist
        assert _run(demo_repo, "--profile", "dev") == 0

    def test_update_allowlist_covers_non_blocking_kinds(self, demo_repo: Path) -> None:
        """Baseline содержит весь долг (в т.ч. missing-класс), scope не влияет."""
        _write_settings(demo_repo, _SETTINGS_SOURCE + _SECRET_CLASS)
        _write_profile(demo_repo, "dev", "secret_demo:\n  api_key: x\n")

        assert _run(demo_repo, "--profile", "dev", "--update-allowlist") == 0
        allowlist = (demo_repo / "allowlist.txt").read_text(encoding="utf-8")
        assert "missing-secret:dev:secret_demo:SECRET_API_KEY" in allowlist
        assert _run(demo_repo, "--profile", "dev") == 0
        assert _run(demo_repo, "--profile", "dev", "--scope", "all") == 0

    def test_strict_fails_on_allowlisted_issues(self, demo_repo: Path) -> None:
        """``--strict`` игнорирует allowlist и падает на любых issues."""
        _write_settings(demo_repo)
        _write_profile(demo_repo, "dev", "demo:\n  known_field: 1\n  typo_field: 2\n")
        (demo_repo / "allowlist.txt").write_text(
            "orphan-key:dev:demo:typo_field  # owner=core | reason=baseline\n",
            encoding="utf-8",
        )

        assert _run(demo_repo, "--profile", "dev") == 0
        assert _run(demo_repo, "--profile", "dev", "--strict") == 1

    def test_missing_profiles_dir_returns_exit_2(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Отсутствие каталога профилей → ошибка запуска (exit 2)."""
        _write_settings(demo_repo)
        (demo_repo / "profiles").rmdir()

        assert _run(demo_repo, "--profile", "dev") == 2
        assert "config_audit" in capsys.readouterr().err

    def test_json_output_reports_new_violations(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """JSON-режим отделяет блокирующие orphan-новости от missing-секции."""
        _write_settings(demo_repo, _SETTINGS_SOURCE + _SECRET_CLASS)
        _write_profile(
            demo_repo,
            "dev",
            "demo:\n  known_field: 1\n  typo_field: 2\nsecret_demo:\n  api_key: x\n",
        )

        assert _run(demo_repo, "--profile", "dev", "--json") == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["new_violations"] == [
            {
                "kind": "orphan-key",
                "profile": "dev",
                "group": "demo",
                "name": "typo_field",
                "key": "orphan-key:dev:demo:typo_field",
            }
        ]
        assert payload["non_blocking"] == [
            {
                "kind": "missing-secret",
                "profile": "dev",
                "group": "secret_demo",
                "name": "SECRET_API_KEY",
                "key": "missing-secret:dev:secret_demo:SECRET_API_KEY",
            }
        ]


class TestRealRepository:
    """Гейт на текущем состоянии репозитория."""

    @pytest.mark.parametrize("profile", PROFILES)
    def test_repo_profiles_have_no_new_violations(self, profile: str) -> None:
        """Фактический долг зафиксирован в baseline, новых нарушений нет."""
        assert main(["--profile", profile]) == 0

    def test_repo_all_profiles_have_no_new_violations(self) -> None:
        """Полный прогон по всем профилям — гейт зелёный."""
        assert main([]) == 0

    def test_repo_orphan_class_is_clean(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """orphan-класс в текущем репозитории пуст (Wave 13 Q17 починил ключи)."""
        assert main(["--profile", "dev"]) == 0
        assert "OK: 0 orphan issues" in capsys.readouterr().out
