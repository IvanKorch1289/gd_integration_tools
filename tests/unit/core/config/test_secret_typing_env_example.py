"""ADR-0378 (wave 15, кластер W3) — необъявленные env-секреты.

Пять секретов читаются напрямую из ``os.environ`` (вне Pydantic Settings),
поэтому гейты конфигурации их не видели: переменные не были перечислены
в ``.env.example``, и на стенде их нельзя было найти по шаблону окружения.

Проверяем два инварианта:

* каждый секрет из списка присутствует в ``.env.example`` с ПУСТЫМ значением
  (правило ADR-0373 «в ``.env`` только секреты»);
* каждый секрет действительно используется в коде (список не устарел).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: Корень репозитория (tests/unit/core/config/<file>.py → parents[4]).
REPO_ROOT = Path(__file__).resolve().parents[4]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
BACKEND_SRC = REPO_ROOT / "src" / "backend"

#: Секреты, читаемые напрямую из ``os.environ`` (без Settings-модели).
UNDECLARED_SECRETS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "LAKERA_API_KEY",
    "NEO4J_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
)


def _env_example_pairs() -> dict[str, str]:
    """Пары ``имя → значение`` из ``.env.example`` (без комментариев)."""
    pairs: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        pairs[name.strip()] = value.strip()
    return pairs


class TestUndeclaredSecretsDocumented:
    """Секреты из ``os.environ`` перечислены в ``.env.example``."""

    @pytest.mark.parametrize("name", UNDECLARED_SECRETS)
    def test_secret_is_listed_in_env_example(self, name: str) -> None:
        """Переменная описана в шаблоне окружения с пустым значением."""
        pairs = _env_example_pairs()
        assert name in pairs, f"{name} не документирован в .env.example"
        assert pairs[name] == "", f"{name} в .env.example должен быть пустым"

    @pytest.mark.parametrize("name", UNDECLARED_SECRETS)
    def test_secret_is_used_in_backend_code(self, name: str) -> None:
        """Переменная реально читается в коде (список не устарел)."""
        used = any(
            name in path.read_text(encoding="utf-8", errors="ignore")
            for path in BACKEND_SRC.rglob("*.py")
        )
        assert used, f"{name} не найден в src/backend — список устарел"
