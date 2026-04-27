"""File-based loader для notification templates (Wave 8.3).

Загружает YAML/TOML файлы из директории ``resources/templates/notifications/``
и регистрирует их в ``TemplateRegistry``. Формат файла:

```yaml
# resources/templates/notifications/kyc_approved.yaml
key: kyc_approved
allowed_channels: [email, telegram]
locales:
  ru:
    subject: "KYC одобрена"
    body: |
      Здравствуйте, {{name}}! Ваша заявка одобрена.
  en:
    subject: "KYC approved"
    body: |
      Hello, {{name}}! Your application is approved.
```

TOML — ровно та же структура. Имя файла без расширения по умолчанию
используется как ``key``, если ``key`` в файле не указан.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from src.infrastructure.notifications.templates import (
    TemplateRegistry,
    get_template_registry,
)

__all__ = (
    "DEFAULT_TEMPLATES_DIR",
    "load_templates_from_dir",
    "load_template_file",
)

_logger = logging.getLogger(__name__)

DEFAULT_TEMPLATES_DIR = Path("resources/templates/notifications")


def _read_yaml(path: Path) -> dict[str, Any]:
    """Читает YAML-файл. PyYAML — soft dep, поэтому импорт ленивый."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "PyYAML недоступен; установите pyyaml для загрузки YAML-шаблонов"
        ) from exc
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _read_toml(path: Path) -> dict[str, Any]:
    """Читает TOML-файл (stdlib tomllib, Python 3.11+)."""
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _read_template_file(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in {".yml", ".yaml"}:
        return _read_yaml(path)
    if suffix == ".toml":
        return _read_toml(path)
    raise ValueError(f"Неподдерживаемый формат шаблона: {path.suffix}")


def load_template_file(
    path: Path | str, *, registry: TemplateRegistry | None = None
) -> str:
    """Загрузить и зарегистрировать ОДИН template-файл. Возвращает ключ."""
    path = Path(path)
    payload = _read_template_file(path)

    key = payload.get("key") or path.stem
    locales = payload.get("locales") or {}
    if not isinstance(locales, dict) or not locales:
        raise ValueError(f"{path}: секция 'locales' пуста")

    allowed = tuple(payload.get("allowed_channels") or ())

    reg = registry or get_template_registry()
    reg.register(key=key, templates=locales, allowed_channels=allowed)
    return key


def load_templates_from_dir(
    directory: Path | str | None = None,
    *,
    registry: TemplateRegistry | None = None,
) -> list[str]:
    """Загружает все ``*.yaml|*.yml|*.toml`` шаблоны из директории.

    Args:
        directory: Каталог шаблонов. По умолчанию — ``DEFAULT_TEMPLATES_DIR``.
        registry: Целевой реестр; если None — глобальный.

    Returns:
        Список зарегистрированных ключей.
    """
    base = Path(directory) if directory else DEFAULT_TEMPLATES_DIR
    if not base.exists():
        _logger.info("templates dir not found, skipping: %s", base)
        return []

    reg = registry or get_template_registry()
    loaded: list[str] = []
    for path in sorted(base.iterdir()):
        if path.suffix.lower() not in {".yaml", ".yml", ".toml"}:
            continue
        try:
            key = load_template_file(path, registry=reg)
            loaded.append(key)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("template skip %s: %s", path, exc)
    _logger.info(
        "templates loaded from disk", extra={"dir": str(base), "count": len(loaded)}
    )
    return loaded
