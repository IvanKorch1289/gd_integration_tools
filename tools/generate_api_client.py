"""Генератор API-клиентов из Postman Collection v2.1 и OpenAPI 3.x.

Парсит спецификацию внешнего API и генерирует:
- Pydantic-схемы (request + response), наследующие BaseSchema
- Сервис-класс (API{Name}Service) по паттерну APISKBService
- Настройки ({Name}APISettings) для конфига
- Фрагмент регистрации actions для setup.py

Использование:
    python tools/generate_api_client.py --source swagger --input docs/api.yaml --name payments
    python tools/generate_api_client.py --source postman --input docs/collection.json --name crm
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from textwrap import dedent, indent

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# ---------------------------------------------------------------------------
#  Утилиты именования
# ---------------------------------------------------------------------------


def snake_to_camel(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def path_to_method_name(method: str, path: str) -> str:
    """Превращает HTTP метод + путь в snake_case имя метода."""
    clean = re.sub(r"\{[^}]+\}", "by_id", path)
    clean = re.sub(r"[^a-zA-Z0-9/]", "", clean)
    parts = [p for p in clean.strip("/").split("/") if p]
    name = "_".join(parts)
    prefix_map = {"GET": "get", "POST": "create", "PUT": "update", "PATCH": "patch", "DELETE": "delete"}
    prefix = prefix_map.get(method.upper(), method.lower())
    if name and not name.startswith(prefix):
        name = f"{prefix}_{name}"
    elif not name:
        name = prefix
    return name.lower()


def sanitize_identifier(name: str) -> str:
    """Делает строку валидным Python-идентификатором."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if name and name[0].isdigit():
        name = f"f_{name}"
    return name or "unnamed"


# ---------------------------------------------------------------------------
#  Маппинг типов
# ---------------------------------------------------------------------------

_OPENAPI_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
}

_FORMAT_MAP: dict[str, str] = {
    "date-time": "datetime",
    "uuid": "UUID",
    "email": "EmailStr",
    "uri": "str",
    "binary": "bytes",
    "date": "date",
}


def _infer_python_type_from_value(value: object) -> str:
    """Выводит тип из примера значения (Postman)."""
    if value is None:
        return "Any | None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        if re.match(r"\d{4}-\d{2}-\d{2}T", value):
            return "datetime"
        if re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            value,
            re.I,
        ):
            return "UUID"
        return "str"
    if isinstance(value, list):
        if value:
            inner = _infer_python_type_from_value(value[0])
            return f"list[{inner}]"
        return "list[Any]"
    if isinstance(value, dict):
        return "dict[str, Any]"
    return "Any"


def _openapi_schema_to_python_type(schema: dict, components: dict | None = None) -> str:
    """Конвертирует OpenAPI schema → Python type string."""
    if "$ref" in schema:
        if components:
            ref_name = schema["$ref"].rsplit("/", 1)[-1]
            resolved = components.get("schemas", {}).get(ref_name, {})
            if resolved.get("type") == "object" and resolved.get("properties"):
                return "dict[str, Any]"
        return "dict[str, Any]"

    oa_type = schema.get("type", "object")
    oa_format = schema.get("format", "")

    if oa_format and oa_format in _FORMAT_MAP:
        return _FORMAT_MAP[oa_format]

    if oa_type == "array":
        items = schema.get("items", {})
        inner = _openapi_schema_to_python_type(items, components)
        return f"list[{inner}]"

    if oa_type == "object":
        return "dict[str, Any]"

    return _OPENAPI_TYPE_MAP.get(oa_type, "Any")


# ---------------------------------------------------------------------------
#  Структуры данных
# ---------------------------------------------------------------------------


class FieldSpec:
    __slots__ = ("name", "python_type", "required", "default", "description")

    def __init__(
        self,
        name: str,
        python_type: str = "Any",
        required: bool = False,
        default: str | None = None,
        description: str = "",
    ) -> None:
        self.name = sanitize_identifier(name)
        self.python_type = python_type
        self.required = required
        self.default = default
        self.description = description

    def render(self) -> str:
        desc = self.description.replace('"', '\\"') if self.description else self.name
        if self.required:
            return f'    {self.name}: {self.python_type} = Field(..., description="{desc}")'
        default_val = self.default if self.default is not None else "None"
        base_type = self.python_type
        if "| None" not in base_type and default_val == "None":
            base_type = f"{base_type} | None"
        return f'    {self.name}: {base_type} = Field(default={default_val}, description="{desc}")'


class EndpointSpec:
    __slots__ = (
        "method", "path", "method_name", "summary",
        "query_params", "path_params", "body_fields", "response_fields",
    )

    def __init__(self) -> None:
        self.method: str = "GET"
        self.path: str = "/"
        self.method_name: str = ""
        self.summary: str = ""
        self.query_params: list[FieldSpec] = []
        self.path_params: list[FieldSpec] = []
        self.body_fields: list[FieldSpec] = []
        self.response_fields: list[FieldSpec] = []


# ---------------------------------------------------------------------------
#  Парсер Postman Collection v2.1
# ---------------------------------------------------------------------------


def _parse_postman_item(item: dict, endpoints: list[EndpointSpec]) -> None:
    """Рекурсивно парсит item/folder из Postman Collection."""
    if "item" in item:
        for sub in item["item"]:
            _parse_postman_item(sub, endpoints)
        return

    req = item.get("request")
    if not req:
        return

    ep = EndpointSpec()
    ep.method = req.get("method", "GET").upper()
    ep.summary = item.get("name", "")

    url = req.get("url", {})
    if isinstance(url, str):
        ep.path = url
    else:
        raw = url.get("raw", "")
        path_parts = url.get("path", [])
        ep.path = "/" + "/".join(path_parts) if path_parts else raw

        for q in url.get("query", []):
            ep.query_params.append(
                FieldSpec(
                    name=q.get("key", "param"),
                    python_type="str",
                    description=q.get("description", ""),
                )
            )

    ep.method_name = path_to_method_name(ep.method, ep.path)

    # Body из примера
    body = req.get("body", {})
    if body.get("mode") == "raw":
        try:
            body_json = json.loads(body.get("raw", "{}"))
            if isinstance(body_json, dict):
                for k, v in body_json.items():
                    ep.body_fields.append(
                        FieldSpec(
                            name=k,
                            python_type=_infer_python_type_from_value(v),
                            required=v is not None,
                        )
                    )
        except json.JSONDecodeError:
            pass

    # Response из примеров
    for resp in item.get("response", []):
        resp_body = resp.get("body", "")
        try:
            resp_json = json.loads(resp_body)
            if isinstance(resp_json, dict):
                for k, v in resp_json.items():
                    ep.response_fields.append(
                        FieldSpec(
                            name=k,
                            python_type=_infer_python_type_from_value(v),
                        )
                    )
                break  # берём первый пример
        except (json.JSONDecodeError, TypeError):
            pass

    endpoints.append(ep)


def parse_postman(data: dict) -> list[EndpointSpec]:
    endpoints: list[EndpointSpec] = []
    for item in data.get("item", []):
        _parse_postman_item(item, endpoints)
    return endpoints


# ---------------------------------------------------------------------------
#  Парсер OpenAPI 3.x
# ---------------------------------------------------------------------------


def _extract_fields_from_schema(schema: dict, components: dict) -> list[FieldSpec]:
    """Извлекает поля из OpenAPI schema object."""
    if "$ref" in schema:
        ref_name = schema["$ref"].rsplit("/", 1)[-1]
        resolved = components.get("schemas", {}).get(ref_name, {})
        return _extract_fields_from_schema(resolved, components)

    props = schema.get("properties", {})
    required_set = set(schema.get("required", []))
    fields: list[FieldSpec] = []

    for name, prop in props.items():
        py_type = _openapi_schema_to_python_type(prop, components)
        fields.append(
            FieldSpec(
                name=name,
                python_type=py_type,
                required=name in required_set,
                description=prop.get("description", ""),
            )
        )
    return fields


def parse_openapi(data: dict) -> list[EndpointSpec]:
    components = data.get("components", {})
    endpoints: list[EndpointSpec] = []

    for path, methods in data.get("paths", {}).items():
        for method, spec in methods.items():
            if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                continue

            ep = EndpointSpec()
            ep.method = method.upper()
            ep.path = path
            ep.summary = spec.get("summary", "")
            ep.method_name = path_to_method_name(ep.method, path)

            for param in spec.get("parameters", []):
                fs = FieldSpec(
                    name=param.get("name", "param"),
                    python_type=_openapi_schema_to_python_type(param.get("schema", {}), components),
                    required=param.get("required", False),
                    description=param.get("description", ""),
                )
                if param.get("in") == "query":
                    ep.query_params.append(fs)
                elif param.get("in") == "path":
                    ep.path_params.append(fs)

            req_body = spec.get("requestBody", {})
            content = req_body.get("content", {})
            json_schema = content.get("application/json", {}).get("schema", {})
            if json_schema:
                ep.body_fields = _extract_fields_from_schema(json_schema, components)

            responses = spec.get("responses", {})
            for code, resp in responses.items():
                if code.startswith("2"):
                    resp_content = resp.get("content", {})
                    resp_schema = resp_content.get("application/json", {}).get("schema", {})
                    if resp_schema:
                        ep.response_fields = _extract_fields_from_schema(resp_schema, components)
                    break

            endpoints.append(ep)

    return endpoints


# ---------------------------------------------------------------------------
#  Рендеринг кода
# ---------------------------------------------------------------------------


def _needs_import(fields: list[FieldSpec], type_name: str) -> bool:
    return any(type_name in f.python_type for f in fields)


def _collect_imports(endpoints: list[EndpointSpec]) -> set[str]:
    """Собирает необходимые импорты для файла схем."""
    all_fields: list[FieldSpec] = []
    for ep in endpoints:
        all_fields.extend(ep.query_params)
        all_fields.extend(ep.path_params)
        all_fields.extend(ep.body_fields)
        all_fields.extend(ep.response_fields)

    imports: set[str] = set()
    if _needs_import(all_fields, "datetime") or _needs_import(all_fields, "date"):
        imports.add("from datetime import date, datetime")
    if _needs_import(all_fields, "UUID"):
        imports.add("from uuid import UUID")
    if _needs_import(all_fields, "EmailStr"):
        imports.add("from pydantic import EmailStr")
    if _needs_import(all_fields, "Any"):
        imports.add("from typing import Any")
    return imports


def render_schemas(name: str, class_prefix: str, endpoints: list[EndpointSpec]) -> str:
    """Генерирует файл Pydantic-схем."""
    extra_imports = _collect_imports(endpoints)
    if not any("from typing import Any" in i for i in extra_imports):
        extra_imports.add("from typing import Any")

    imports_block = "\n".join(sorted(extra_imports))

    lines = [
        f'"""Pydantic-схемы для {name} API.',
        "",
        "Сгенерировано автоматически из Postman Collection / OpenAPI.",
        "Все схемы наследуют BaseSchema → camelCase алиасы, from_attributes.",
        '"""',
        "",
        imports_block,
        "",
        "from pydantic import Field",
        "",
        "from app.schemas.base import BaseSchema",
        "",
        "",
        f"class {class_prefix}BaseResponse(BaseSchema):",
        f'    """Базовый ответ {name} API."""',
        '    success: bool = Field(default=True, description="Признак успешности")',
        '    error: str | None = Field(default=None, description="Сообщение об ошибке")',
    ]

    all_names = [f"{class_prefix}BaseResponse"]

    for ep in endpoints:
        method_camel = snake_to_camel(ep.method_name)

        # Request schema
        if ep.body_fields or ep.query_params or ep.path_params:
            req_name = f"{class_prefix}{method_camel}Request"
            all_names.append(req_name)
            lines.append("")
            lines.append("")
            lines.append(f"class {req_name}(BaseSchema):")
            lines.append(f'    """{ep.method} {ep.path} — запрос."""')
            all_params = ep.path_params + ep.query_params + ep.body_fields
            if all_params:
                for f in all_params:
                    lines.append(f.render())
            else:
                lines.append("    pass")

        # Response schema
        if ep.response_fields:
            resp_name = f"{class_prefix}{method_camel}Response"
            all_names.append(resp_name)
            lines.append("")
            lines.append("")
            lines.append(f"class {resp_name}({class_prefix}BaseResponse):")
            lines.append(f'    """{ep.method} {ep.path} — ответ."""')
            for f in ep.response_fields:
                lines.append(f.render())

    # __all__
    all_str = ", ".join(f'"{n}"' for n in all_names)
    header = [
        "",
        f"__all__ = ({all_str},)",
        "",
    ]

    final_lines = lines[:1] + lines[1:6] + header + lines[6:]
    return "\n".join(final_lines) + "\n"


def render_service(name: str, class_prefix: str, endpoints: list[EndpointSpec]) -> str:
    """Генерирует файл сервис-класса."""
    methods_code: list[str] = []

    for ep in endpoints:
        params: list[str] = ["self"]
        for f in ep.path_params:
            params.append(f"{f.name}: {f.python_type}")
        for f in ep.body_fields:
            if f.required:
                params.append(f"{f.name}: {f.python_type}")
        for f in ep.query_params:
            params.append(f"{f.name}: {f.python_type} = None")
        for f in ep.body_fields:
            if not f.required:
                params.append(f"{f.name}: {f.python_type} = None")

        sig = ", ".join(params)
        # URL с path-параметрами
        url_path = ep.path
        for pp in ep.path_params:
            url_path = re.sub(r"\{[^}]+\}", f"{{{pp.name}}}", url_path, count=1)

        # Собираем query params
        qp_lines: list[str] = []
        for qp in ep.query_params:
            qp_lines.append(f'        if {qp.name} is not None:')
            qp_lines.append(f'            params["{qp.name}"] = {qp.name}')

        # Собираем body
        body_fields = [f for f in ep.body_fields]
        json_lines: list[str] = []
        if body_fields:
            json_lines.append("        json_body: dict[str, Any] = {}")
            for bf in body_fields:
                if bf.required:
                    json_lines.append(f'        json_body["{bf.name}"] = {bf.name}')
                else:
                    json_lines.append(f'        if {bf.name} is not None:')
                    json_lines.append(f'            json_body["{bf.name}"] = {bf.name}')

        method_code = [
            f"    async def {ep.method_name}({sig}) -> dict[str, Any]:",
            f'        """{ep.method} {ep.path} — {ep.summary or ep.method_name}."""',
            "        try:",
        ]

        if qp_lines:
            method_code.append("            params: dict[str, Any] = {}")
            method_code.extend(["    " + l for l in qp_lines])

        if json_lines:
            method_code.extend(["    " + l for l in json_lines])

        # URL
        if ep.path_params:
            method_code.append(f'            url = self._url(f"{url_path}")')
        else:
            method_code.append(f'            url = self._url("{url_path}")')

        # make_request
        req_kwargs = [
            f'                method="{ep.method}",',
            "                url=url,",
        ]
        if qp_lines:
            req_kwargs.append("                params=params or None,")
        if body_fields:
            req_kwargs.append("                json=json_body,")
        req_kwargs.extend([
            "                headers=self._auth_headers(),",
            "                connect_timeout=self._settings.connect_timeout,",
            "                read_timeout=self._settings.read_timeout,",
            "                total_timeout=self._settings.connect_timeout + self._settings.read_timeout,",
        ])

        method_code.append("            return await self._client.make_request(")
        method_code.extend(req_kwargs)
        method_code.append("            )")
        method_code.append("        except Exception as exc:")
        method_code.append(
            f'            raise ServiceError(detail=f"{class_prefix} {ep.method_name} error: {{exc}}") from exc'
        )

        methods_code.append("\n".join(method_code))

    methods_block = "\n\n".join(methods_code)

    return dedent(f'''\
        """Сервис интеграции с {name} API.

        Сгенерирован автоматически из Postman Collection / OpenAPI.
        """

        from typing import Any
        from urllib.parse import urljoin

        from app.core.config.settings import settings
        from app.core.errors import ServiceError
        from app.infrastructure.clients.transport.http import get_http_client_dependency

        __all__ = ("API{class_prefix}Service", "get_{name}_service")


        class API{class_prefix}Service:
            """Сервис интеграции с {name} API."""

            def __init__(self) -> None:
                self._settings = settings.{name}_api
                self._client = get_http_client_dependency()

            def _url(self, path: str) -> str:
                return urljoin(self._settings.base_url, path)

            def _auth_headers(self) -> dict[str, str]:
                if self._settings.api_key:
                    return {{"Authorization": f"Bearer {{self._settings.api_key}}"}}
                return {{}}

    ''') + indent(methods_block, "") + "\n\n\n" + dedent(f'''\
        _{name}_service_instance: "API{class_prefix}Service | None" = None


        def get_{name}_service() -> API{class_prefix}Service:
            global _{name}_service_instance
            if _{name}_service_instance is None:
                _{name}_service_instance = API{class_prefix}Service()
            return _{name}_service_instance
    ''')


def render_settings(name: str, class_prefix: str) -> str:
    """Генерирует файл настроек."""
    env_prefix = name.upper() + "_"
    return dedent(f'''\
        """Настройки {name} API.

        Переменные окружения с префиксом {env_prefix}.
        """

        from pydantic import Field
        from pydantic_settings import BaseSettings

        __all__ = ("{class_prefix}APISettings",)


        class {class_prefix}APISettings(BaseSettings):
            """Настройки подключения к {name} API."""

            base_url: str = Field(..., description="Базовый URL API")
            api_key: str = Field(default="", description="API-ключ или Bearer-токен")
            connect_timeout: float = Field(default=10.0, description="Таймаут подключения (сек)")
            read_timeout: float = Field(default=30.0, description="Таймаут чтения (сек)")

            model_config = {{"env_prefix": "{env_prefix}"}}
    ''')


def render_actions_fragment(name: str, class_prefix: str, endpoints: list[EndpointSpec]) -> str:
    """Генерирует фрагмент для setup.py."""
    lines = [
        f"# --- {name} API actions ---",
        f"from app.services.{name} import get_{name}_service",
        "",
    ]

    for ep in endpoints:
        schema_import = ""
        has_body = bool(ep.body_fields or ep.query_params or ep.path_params)
        if has_body:
            method_camel = snake_to_camel(ep.method_name)
            schema_class = f"{class_prefix}{method_camel}Request"
            schema_import = f"  # payload_model: {schema_class}"

        lines.append(f'action_handler_registry.register(')
        lines.append(f'    action="{name}.{ep.method_name}",')
        lines.append(f'    service_getter=get_{name}_service,')
        lines.append(f'    service_method="{ep.method_name}",{schema_import}')
        lines.append(f')')

    return "\n".join(lines)


# ---------------------------------------------------------------------------
#  Основная логика
# ---------------------------------------------------------------------------


def write_file(path: Path, content: str, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        print(f"  SKIP (exists): {path.relative_to(ROOT)}")
        return
    path.write_text(content, encoding="utf-8")
    print(f"  CREATED: {path.relative_to(ROOT)}")


def load_input(input_path: Path) -> dict:
    text = input_path.read_text(encoding="utf-8")
    if input_path.suffix in (".yaml", ".yml"):
        try:
            import yaml
            return yaml.safe_load(text)
        except ImportError:
            print("ERROR: pyyaml required for YAML files. Install: pip install pyyaml", file=sys.stderr)
            sys.exit(1)
    return json.loads(text)


def detect_source(data: dict) -> str:
    if "openapi" in data:
        return "swagger"
    if "info" in data and "item" in data:
        return "postman"
    return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Генератор API-клиентов из Postman Collection / OpenAPI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            Примеры:
              python tools/generate_api_client.py --input docs/petstore.yaml --name petstore
              python tools/generate_api_client.py --input docs/collection.json --name crm
              python tools/generate_api_client.py --source postman --input api.json --name payments --force
        """),
    )
    parser.add_argument("--source", choices=["swagger", "postman", "auto"], default="auto",
                        help="Тип источника (auto — определить автоматически)")
    parser.add_argument("--input", required=True, help="Путь к файлу спецификации")
    parser.add_argument("--name", required=True, help="Имя сервиса в snake_case (например: external_crm)")
    parser.add_argument("--force", action="store_true", help="Перезаписать существующие файлы")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    name = args.name.strip().lower()
    if not name.isidentifier():
        print(f"ERROR: '{name}' is not a valid Python identifier", file=sys.stderr)
        sys.exit(1)

    class_prefix = snake_to_camel(name)

    print(f"Loading {input_path}...")
    data = load_input(input_path)

    source = args.source
    if source == "auto":
        source = detect_source(data)
        if source == "unknown":
            print("ERROR: Cannot detect source type. Use --source explicitly.", file=sys.stderr)
            sys.exit(1)
        print(f"  Detected: {source}")

    print("Parsing endpoints...")
    if source == "postman":
        endpoints = parse_postman(data)
    else:
        endpoints = parse_openapi(data)

    if not endpoints:
        print("WARNING: No endpoints found!", file=sys.stderr)
        sys.exit(1)

    print(f"  Found {len(endpoints)} endpoint(s)")
    for ep in endpoints:
        print(f"    {ep.method:6s} {ep.path} -> {ep.method_name}()")

    # Генерация файлов
    print("\nGenerating files...")

    schema_path = SRC / "schemas" / "route_schemas" / f"{name}.py"
    service_path = SRC / "services" / f"{name}.py"
    settings_path = SRC / "core" / "config" / f"{name}_settings.py"

    write_file(schema_path, render_schemas(name, class_prefix, endpoints), args.force)
    write_file(service_path, render_service(name, class_prefix, endpoints), args.force)
    write_file(settings_path, render_settings(name, class_prefix), args.force)

    # Фрагмент для setup.py
    print("\n" + "=" * 60)
    print("Фрагмент для src/dsl/commands/setup.py:")
    print("=" * 60)
    print(render_actions_fragment(name, class_prefix, endpoints))
    print("=" * 60)

    print(f"\nDone! Generated {len(endpoints)} methods for {class_prefix}.")
    print(f"Don't forget to add {class_prefix}APISettings to your settings.py!")


if __name__ == "__main__":
    main()
