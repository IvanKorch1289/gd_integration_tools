"""Гейт обновления Pillow 12 → 13 (ADR-0406, волна 22, кластер B2).

Задача: снять пин ``pillow<13.0.0``, которым были закрыты **59 CVE
(5 CRIT)** Pillow 12.3.0. Пин держался не из-за кода, а из-за
``streamlit``: версии до 1.66.1 требовали ``pillow<13``, поэтому
``pillow>=13`` делал lock-файл неразрешимым.

Тест проверяет **семантику** ограничений (через ``packaging``), а не
наличие подстроки в файле:

* каждый объявленный спецификатор ``pillow`` (core + extras) допускает
  13.0.0 и не допускает 14.0.0;
* объявленный пол ``streamlit`` допускает 1.66.1 — первую версию, снявшую
  ограничение ``pillow<13``;
* ``uv.lock`` закрепляет ``pillow>=13.0.0`` и ``streamlit>=1.66.1``;
* **установленный** дистрибутив ``streamlit`` действительно разрешает
  ``pillow>=13`` (проверка через ``importlib.metadata``, а не по догадке);
* установленный Pillow — 13.x и содержит весь API, который использует
  проект (``Image.open``, ``MAX_IMAGE_PIXELS``, ``DecompressionBomb*``);
* ``open_image`` — единая точка безопасной загрузки изображений — работает
  на текущем Pillow (открытие → ресайз → сохранение PNG).
"""

from __future__ import annotations

import io
import tomllib
from importlib import metadata
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
UV_LOCK = REPO_ROOT / "uv.lock"

#: Целевая версия Pillow (первая, закрывающая CVE из 59).
PILLOW_TARGET = Version("13.0.0")

#: Первая версия streamlit, снявшая ограничение ``pillow<13``.
#: 1.64.0/1.65.0 → ``pillow>=7.1.0,<13``; 1.66.0 → ``pillow>=9.2.0,<13``;
#: 1.66.1 → ``pillow>=9.2.0,<14``.
STREAMLIT_PILLOW13_MIN = Version("1.66.1")


def _declared_requirements() -> list[Requirement]:
    """Все требования проекта: core-зависимости + все extras.

    Returns:
        Разобранные требования из ``pyproject.toml``.

    """
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    raw: list[str] = list(data["project"]["dependencies"])
    for extra_deps in data["project"].get("optional-dependencies", {}).values():
        raw.extend(extra_deps)
    return [Requirement(item) for item in raw]


def _locked_version(package: str) -> Version:
    """Версия пакета, закреплённая в ``uv.lock``.

    Args:
        package: Имя дистрибутива.

    Returns:
        Версия из lock-файла.

    Raises:
        AssertionError: Пакет не найден в lock-файле.

    """
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    for entry in lock["package"]:
        if entry["name"] == package:
            return Version(entry["version"])
    raise AssertionError(f"пакет {package!r} не найден в uv.lock")


@pytest.mark.unit
class TestDeclaredPillowConstraints:
    """Семантика объявленных спецификаторов ``pillow``."""

    def test_every_pillow_specifier_allows_13(self) -> None:
        """Все объявленные ``pillow``-спецификаторы допускают 13.0.0."""
        pillow_specs = [
            req.specifier for req in _declared_requirements() if req.name == "pillow"
        ]
        assert pillow_specs, "pillow не объявлен ни в core, ни в extras"
        broken = [
            str(spec) for spec in pillow_specs if not spec.contains(PILLOW_TARGET)
        ]
        assert not broken, (
            "спецификаторы pillow не допускают 13.0.0: "
            f"{broken} — пин <13.0.0 не снят (ADR-0406)"
        )

    def test_pillow_upper_bound_stays_below_14(self) -> None:
        """Верхняя граница ``pillow`` остаётся ``<14`` (pillow 14 — major)."""
        pillow_specs = [
            req.specifier for req in _declared_requirements() if req.name == "pillow"
        ]
        leaking = [
            str(spec) for spec in pillow_specs if spec.contains(Version("14.0.0"))
        ]
        assert not leaking, f"спецификаторы pillow допускают 14.x: {leaking}"


@pytest.mark.unit
class TestDeclaredStreamlitConstraint:
    """Пол ``streamlit`` должен допускать версию, снявшую ``pillow<13``."""

    def test_streamlit_floor_allows_pillow13_release(self) -> None:
        """Нижняя граница ``streamlit`` — не ниже 1.66.1 (первый с ``pillow<14``)."""
        streamlit_specs = [
            req.specifier for req in _declared_requirements() if req.name == "streamlit"
        ]
        assert streamlit_specs, "streamlit не объявлен"
        floors: list[Version] = []
        unbounded: list[str] = []
        for spec in streamlit_specs:
            lower = [
                Version(item.version)
                for item in spec
                if item.operator in {">=", "==", "~="} and item.version
            ]
            if not lower:
                unbounded.append(str(spec))
                continue
            floors.append(min(lower))
        assert not unbounded, (
            f"спецификаторы streamlit без нижней границы: {unbounded} — "
            "резолвер может выбрать версию с pillow<13 (ADR-0406)"
        )
        broken = [
            str(spec)
            for spec, floor in zip(streamlit_specs, floors, strict=False)
            if floor < STREAMLIT_PILLOW13_MIN
        ]
        assert not broken, (
            "нижняя граница streamlit ниже 1.66.1: "
            f"{broken} — при streamlit<1.66.1 pillow>=13 неразрешим (ADR-0406)"
        )


@pytest.mark.unit
class TestLockFile:
    """``uv.lock`` закрепляет новые версии."""

    def test_lock_pins_pillow_13(self) -> None:
        """В lock-файле закреплён Pillow 13.x."""
        assert _locked_version("pillow") >= PILLOW_TARGET

    def test_lock_pins_streamlit_with_pillow13_support(self) -> None:
        """В lock-файле закреплён streamlit >= 1.66.1."""
        assert _locked_version("streamlit") >= STREAMLIT_PILLOW13_MIN


@pytest.mark.unit
class TestInstalledDistributions:
    """Фактически установленные дистрибутивы."""

    def test_installed_pillow_is_13_or_newer(self) -> None:
        """Установлен Pillow 13.x."""
        installed = Version(metadata.version("pillow"))
        assert installed >= PILLOW_TARGET, (
            f"установлен pillow {installed}, ожидается >= {PILLOW_TARGET}"
        )

    def test_installed_streamlit_permits_pillow_13(self) -> None:
        """Метаданные установленного streamlit разрешают pillow 13."""
        requires = metadata.requires("streamlit") or []
        pillow_specs = [
            Requirement(item).specifier
            for item in requires
            if Requirement(item).name == "pillow"
        ]
        assert pillow_specs, "streamlit не декларирует зависимость pillow"
        broken = [
            str(spec) for spec in pillow_specs if not spec.contains(PILLOW_TARGET)
        ]
        assert not broken, (
            f"установленный streamlit ограничивает pillow: {broken} — "
            "обновление streamlit не состоялось (ADR-0406)"
        )

    def test_pillow_api_used_by_project_is_present(self) -> None:
        """Весь API Pillow, который использует проект, доступен в 13.x."""
        image_module = pytest.importorskip("PIL.Image")
        for attribute in (
            "open",
            "MAX_IMAGE_PIXELS",
            "DecompressionBombWarning",
            "DecompressionBombError",
            "UnidentifiedImageError",
        ):
            assert hasattr(image_module, attribute), (
                f"PIL.Image.{attribute} отсутствует — pillow 13 изменил API"
            )
        for method in ("convert", "resize", "save", "load", "getexif"):
            assert hasattr(image_module.Image, method), (
                f"PIL.Image.Image.{method} отсутствует — pillow 13 изменил API"
            )


@pytest.mark.unit
class TestImagePipelineOnInstalledPillow:
    """Функциональная проверка загрузки/ресайза изображений."""

    def test_open_image_resize_and_save_roundtrip(self) -> None:
        """``open_image`` открывает изображение, ресайз и сохранение работают."""
        from PIL import Image

        from src.backend.core.utils.image_safety import open_image

        buffer = io.BytesIO()
        Image.new("RGB", (16, 16), (10, 20, 30)).save(buffer, format="PNG")
        payload = buffer.getvalue()

        with open_image(payload) as image:
            resized = image.resize((8, 8))
            out = io.BytesIO()
            resized.save(out, format="PNG")

        with Image.open(io.BytesIO(out.getvalue())) as result:
            assert result.size == (8, 8)
            assert result.format == "PNG"
