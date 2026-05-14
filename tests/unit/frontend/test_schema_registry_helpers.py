"""Тесты вспомогательных функций Schema Registry (без Streamlit runtime).

Покрывает четыре публичных функции из
:mod:`src.frontend.streamlit_app.services.schema_registry_client`:

- :func:`list_schemas` — листинг файлов по типу;
- :func:`read_schema` — чтение содержимого файла;
- :func:`validate_openapi` — базовая валидация JSON/YAML-схем;
- :func:`diff_schemas` — unified-diff двух версий.

Streamlit не импортируется и не запускается.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.frontend.streamlit_app.services.schema_registry_client import (
    diff_schemas,
    list_schemas,
    read_schema,
    validate_openapi,
)


class TestListSchemas:
    """Тесты функции list_schemas."""

    def test_list_schemas_empty_dir(self, tmp_path: Path) -> None:
        """list_schemas возвращает пустой список для несуществующей директории.

        Проверяет корректную обработку случая когда каталог схем ещё
        не создан (начальный стейт репозитория или изолированный тест).
        """
        with patch(
            "src.frontend.streamlit_app.services.schema_registry_client._SCHEMAS_BASE",
            tmp_path / "nonexistent",
        ):
            result = list_schemas("openapi")

        assert result == []

    def test_list_schemas_finds_files(self, tmp_path: Path) -> None:
        """list_schemas находит файлы с корректными расширениями.

        Создаёт временную директорию с тестовыми файлами и проверяет,
        что функция возвращает все файлы с поддерживаемыми расширениями.
        """
        openapi_dir = tmp_path / "openapi"
        openapi_dir.mkdir(parents=True)
        (openapi_dir / "api.yaml").write_text("openapi: 3.0.0", encoding="utf-8")
        (openapi_dir / "admin.json").write_text("{}", encoding="utf-8")
        (openapi_dir / "readme.txt").write_text("ignore me", encoding="utf-8")

        with patch(
            "src.frontend.streamlit_app.services.schema_registry_client._SCHEMAS_BASE",
            tmp_path,
        ):
            result = list_schemas("openapi")

        names = {p.name for p in result}
        assert "api.yaml" in names
        assert "admin.json" in names
        assert "readme.txt" not in names

    def test_list_schemas_unknown_kind_returns_empty(self) -> None:
        """list_schemas возвращает пустой список для неизвестного kind.

        Неизвестный тип схемы не должен вызывать исключение — только
        возвращать пустой список.
        """
        result = list_schemas("unknown_kind_xyz")
        assert result == []


class TestReadSchema:
    """Тесты функции read_schema."""

    def test_read_schema_returns_content(self, tmp_path: Path) -> None:
        """read_schema возвращает текстовое содержимое файла.

        Создаёт временный файл с известным контентом и проверяет,
        что функция возвращает его без изменений.
        """
        schema_file = tmp_path / "test.yaml"
        expected = "openapi: 3.0.0\ninfo:\n  title: Test\n"
        schema_file.write_text(expected, encoding="utf-8")

        result = read_schema(schema_file)

        assert result == expected

    def test_read_schema_raises_on_missing_file(self, tmp_path: Path) -> None:
        """read_schema бросает FileNotFoundError для несуществующего файла.

        Функция не должна глотать ошибки файловой системы — исключение
        обрабатывается на уровне Streamlit UI.
        """
        missing = tmp_path / "missing.yaml"
        with pytest.raises(FileNotFoundError):
            read_schema(missing)


class TestValidateOpenapi:
    """Тесты функции validate_openapi."""

    def test_validate_openapi_valid_document(self) -> None:
        """validate_openapi возвращает True для корректного OpenAPI 3.0 документа.

        Минимально валидный OpenAPI-документ с обязательными ключами должен
        проходить санитарную проверку без ошибок.
        """
        doc = json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "Test API", "version": "1.0.0"},
                "paths": {},
            }
        )
        is_valid, msg = validate_openapi(doc)
        assert is_valid is True
        assert "3.0.0" in msg

    def test_validate_openapi_invalid_json(self) -> None:
        """validate_openapi возвращает False для невалидного JSON/YAML.

        Синтаксически некорректный контент не должен вызывать исключение —
        функция обязана вернуть (False, описание_ошибки).
        """
        invalid_content = "{ this is not valid json or yaml !!!"
        # Мокаем yaml чтобы он тоже упал на этом контенте
        mock_yaml = MagicMock()
        mock_yaml.safe_load.side_effect = Exception("yaml parse error")
        with patch.dict("sys.modules", {"yaml": mock_yaml}):
            is_valid, msg = validate_openapi(invalid_content)

        assert is_valid is False
        assert msg  # сообщение не пустое

    def test_validate_openapi_missing_required_keys(self) -> None:
        """validate_openapi возвращает False если отсутствуют обязательные ключи.

        OpenAPI-документ без ключа ``paths`` не является валидным —
        функция должна сообщить об отсутствующих полях.
        """
        doc = json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "Incomplete"},
                # "paths" намеренно отсутствует
            }
        )
        is_valid, msg = validate_openapi(doc)
        assert is_valid is False
        assert "paths" in msg

    def test_validate_asyncapi_valid(self) -> None:
        """validate_openapi распознаёт и валидирует AsyncAPI документ.

        AsyncAPI с обязательными ключами ``asyncapi`` и ``info`` должен
        проходить проверку успешно.
        """
        doc = json.dumps(
            {
                "asyncapi": "2.6.0",
                "info": {"title": "Events API", "version": "1.0.0"},
                "channels": {},
            }
        )
        is_valid, msg = validate_openapi(doc)
        assert is_valid is True
        assert "AsyncAPI" in msg


class TestDiffSchemas:
    """Тесты функции diff_schemas."""

    def test_diff_schemas_returns_unified_diff(self) -> None:
        """diff_schemas возвращает непустой unified-diff для разных схем.

        Функция должна выдавать стандартный unified-diff формат (строки
        с +/-/@@) при наличии различий между двумя версиями схемы.
        """
        schema_a = "openapi: 3.0.0\ninfo:\n  title: API v1\n"
        schema_b = "openapi: 3.0.0\ninfo:\n  title: API v2\n"

        result = diff_schemas(schema_a, schema_b)

        assert result != ""
        assert "schema_a" in result
        assert "schema_b" in result
        assert "-  title: API v1" in result
        assert "+  title: API v2" in result

    def test_diff_schemas_identical_returns_empty(self) -> None:
        """diff_schemas возвращает пустую строку для идентичных схем.

        При отсутствии различий функция не должна генерировать вывод —
        это позволяет UI отобразить сообщение «схемы идентичны».
        """
        schema = "openapi: 3.0.0\ninfo:\n  title: Same\n"
        result = diff_schemas(schema, schema)
        assert result == ""

    def test_diff_schemas_empty_inputs(self) -> None:
        """diff_schemas корректно обрабатывает пустые строки.

        Пустые входные данные не должны вызывать исключение.
        """
        result = diff_schemas("", "")
        assert result == ""
