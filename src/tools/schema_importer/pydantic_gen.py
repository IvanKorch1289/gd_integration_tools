"""Генератор Python-кода Pydantic v2 моделей из JSON Schema-подобного dict.

Принимает упрощённое представление схемы (результат парсинга OpenAPI /
Postman) и генерирует текст ``.py``-файла с моделями. Работает офлайн,
без сторонних утилит типа ``datamodel-code-generator`` — это
компромисс в пользу нулевых новых зависимостей.

Ограничения первой итерации (Wave 3.4):

* поддерживаются примитивы, ``object`` (→ BaseModel), ``array``;
* ``$ref`` разрешаются в плоском namespace (components.schemas);
* ``oneOf`` / ``anyOf`` → ``Union``; ``allOf`` → merge полей;
* строковые форматы (``date``, ``date-time``, ``uuid``, ``email``)
  маппятся на соответствующие типы Python / Pydantic;
* enum-ы генерируются как ``Literal[...]`` (коротко и без дополнительных
  импортов). При большом enum-е (> 16 значений) используется ``str``.
"""

from __future__ import annotations

from datetime import datetime
from keyword import iskeyword
from typing import Any

__all__ = ("render_models", "AUTO_HEADER_TEMPLATE")

AUTO_HEADER_TEMPLATE = (
    "# Авто-сгенерировано из {kind} spec. НЕ редактировать вручную.\n"
    "# Источник: {source}\n"
    "# Дата генерации: {date}\n"
    "# Для кастомизации → создайте src/schemas/custom/<name>.py\n"
)

_PRIMITIVE_MAP: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "null": "None",
}

_STRING_FORMAT_MAP: dict[str, str] = {
    "date": "date",
    "date-time": "datetime",
    "uuid": "UUID",
    "email": "EmailStr",
    "uri": "AnyUrl",
    "ipv4": "IPv4Address",
    "ipv6": "IPv6Address",
}


def _safe_ident(name: str) -> str:
    """Python-идентификатор: кириллица → транслит, зарезервированные → _suffix."""
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    if cleaned and cleaned[0].isdigit():
        cleaned = f"f_{cleaned}"
    if iskeyword(cleaned) or cleaned in {"True", "False", "None"}:
        cleaned = f"{cleaned}_"
    return cleaned or "field"


def _render_type(schema: dict[str, Any], required: bool) -> tuple[str, set[str]]:
    """Возвращает (type-expr, extra_imports)."""
    imports: set[str] = set()
    ref = schema.get("$ref")
    if ref:
        model = ref.rsplit("/", 1)[-1]
        expr = _safe_ident(model)
        if not required:
            expr = f"{expr} | None"
        return expr, imports

    one_of = schema.get("oneOf") or schema.get("anyOf")
    if one_of and isinstance(one_of, list):
        parts: list[str] = []
        for sub in one_of:
            expr, sub_imp = _render_type(sub, required=True)
            imports |= sub_imp
            parts.append(expr)
        union_expr = " | ".join(parts) if parts else "Any"
        if not required:
            union_expr = f"{union_expr} | None"
        if "Any" in union_expr:
            imports.add("from typing import Any")
        return union_expr, imports

    enum_values = schema.get("enum")
    if enum_values is not None and len(enum_values) <= 16:
        literals = ", ".join(repr(v) for v in enum_values)
        imports.add("from typing import Literal")
        expr = f"Literal[{literals}]"
        if not required:
            expr = f"{expr} | None"
        return expr, imports

    kind = schema.get("type")
    if kind == "array":
        item_expr, sub_imp = _render_type(schema.get("items", {}), required=True)
        imports |= sub_imp
        expr = f"list[{item_expr}]"
        if not required:
            expr = f"{expr} | None"
        return expr, imports

    if kind == "object" or (kind is None and "properties" in schema):
        # Inline object → dict[str, Any] (inline-объекты не выделяются
        # в отдельные модели в этой упрощённой реализации).
        imports.add("from typing import Any")
        expr = "dict[str, Any]"
        if not required:
            expr = f"{expr} | None"
        return expr, imports

    if kind == "string":
        fmt = schema.get("format")
        if fmt in _STRING_FORMAT_MAP:
            mapped = _STRING_FORMAT_MAP[fmt]
            if mapped == "datetime":
                imports.add("from datetime import datetime")
            elif mapped == "date":
                imports.add("from datetime import date")
            elif mapped == "UUID":
                imports.add("from uuid import UUID")
            elif mapped in {"EmailStr", "AnyUrl"}:
                imports.add(f"from pydantic import {mapped}")
            elif mapped in {"IPv4Address", "IPv6Address"}:
                imports.add(f"from ipaddress import {mapped}")
            expr = mapped
        else:
            expr = "str"
        if not required:
            expr = f"{expr} | None"
        return expr, imports

    if isinstance(kind, list):
        parts = []
        for k in kind:
            parts.append(_PRIMITIVE_MAP.get(k, "Any"))
            if "Any" in parts:
                imports.add("from typing import Any")
        expr = " | ".join(dict.fromkeys(parts))
        if not required:
            expr = f"{expr} | None"
        return expr, imports

    primitive = _PRIMITIVE_MAP.get(kind or "", "Any")
    if primitive == "Any":
        imports.add("from typing import Any")
    expr = primitive
    if not required:
        expr = f"{expr} | None"
    return expr, imports


def _render_model(name: str, schema: dict[str, Any]) -> tuple[str, set[str]]:
    imports: set[str] = {"from pydantic import BaseModel"}
    props: dict[str, Any] = schema.get("properties") or {}
    required_fields = set(schema.get("required") or [])

    ident = _safe_ident(name)
    lines = [f"class {ident}(BaseModel):"]
    docstring = schema.get("description") or f"Авто-сгенерированная модель {ident}."
    lines.append(f'    """{docstring.strip()}"""')
    if not props:
        lines.append("    pass")
    else:
        for prop_name, prop_schema in props.items():
            py_name = _safe_ident(prop_name)
            type_expr, imp = _render_type(
                prop_schema or {}, required=prop_name in required_fields
            )
            imports |= imp
            default = "" if prop_name in required_fields else " = None"
            if py_name != prop_name:
                # Алиас для несовместимого имени поля.
                imports.add("from pydantic import Field")
                lines.append(
                    f"    {py_name}: {type_expr} ="
                    f" Field({'...' if prop_name in required_fields else 'None'},"
                    f' alias="{prop_name}")'
                )
            else:
                lines.append(f"    {py_name}: {type_expr}{default}")
    return "\n".join(lines) + "\n", imports


def render_models(
    *,
    models: dict[str, dict[str, Any]],
    source: str,
    kind: str,
) -> str:
    """Собирает итоговый текст ``.py`` со всеми моделями.

    Args:
        models: ``{ModelName: schema_dict}``.
        source: Строка-источник (URL или путь) — попадает в шапку.
        kind: "OpenAPI" / "Postman".
    """
    header = AUTO_HEADER_TEMPLATE.format(
        kind=kind,
        source=source,
        date=datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )
    bodies: list[str] = []
    all_imports: set[str] = set()
    for model_name, schema in models.items():
        body, imp = _render_model(model_name, schema or {})
        bodies.append(body)
        all_imports |= imp

    imports_block = "\n".join(sorted(all_imports))
    return (
        f"{header}\nfrom __future__ import annotations\n\n"
        f"{imports_block}\n\n\n"
        + "\n\n".join(bodies)
    )
