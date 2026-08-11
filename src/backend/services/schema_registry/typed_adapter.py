"""TypedAdapter wrapper для public API boundary (D-AUDIT-A5-01 fix, cycle 1).

Audit D-A5-01 (P0) — ``ServiceSchemaRegistry`` имеет методы, возвращающие
``dict[str, Any]`` для untyped payload на публичной границе (``to_snapshot``
→ ``dict[str, Any]``, ``from_snapshot`` принимает ``data: dict[str, Any]``).
Поля :class:`SchemaEntry` (``spec_schema`` / ``output_schema`` / ``meta``) —
также ``dict[str, Any]``. Это допустимо для метаданных (они по природе
free-form), но публичная граница API требует type safety.

Этот модуль предоставляет :class:`SchemaTypedAdapter` — тонкий typed wrapper,
который:

* Обёртывает :class:`SchemaEntry` в :class:`SchemaEntryView` без изменения
  internals (``SchemaEntry`` остаётся frozen dataclass).
* Использует :class:`pydantic.TypeAdapter` для runtime validation payload'ов
  ``to_snapshot`` / ``from_snapshot`` на public boundary.
* Предоставляет round-trip :meth:`SchemaEntryView.to_json_dict` /
  :meth:`SchemaEntryView.from_json_dict` для safe (de)serialization.

Pattern: 80% declarative (Pydantic TypeAdapter) + 20% Python facade.
Docstring marker: ``D-AUDIT-A5-01 fix (cycle 1)``.
"""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from src.backend.services.schema_registry.registry import (
    CURRENT_SNAPSHOT_VERSION,
    SchemaEntry,
    SchemaKind,
)

__all__ = ("SchemaEntryView", "SchemaTypedAdapter", "SnapshotView")

# Module-level TypeAdapter singletons (Pydantic v2: cheap to construct but
# re-using instances is canonical best practice).
_DICT_ADAPTER: TypeAdapter[dict[str, Any]] = TypeAdapter(dict[str, Any])
_LIST_ADAPTER: TypeAdapter[list[dict[str, Any]]] = TypeAdapter(list[dict[str, Any]])


class SchemaTypedAdapter:
    """Typed wrapper для public API boundary (:class:`SchemaEntry` + snapshot).

    Не изменяет :class:`SchemaEntry` internals — frozen dataclass остаётся
    первоисточником правды. Адаптер только обогащает публичную поверхность
    type-safe ``(de)serialization`` через :class:`pydantic.TypeAdapter`.

    Использование::

        adapter = SchemaTypedAdapter()
        view = adapter.entry_view(entry)
        payload = view.to_json_dict()
        restored = adapter.entry_from_dict(payload)
        snapshot = SnapshotView.from_json_dict(reg.to_snapshot())
    """

    __slots__ = ()

    def entry_view(self, entry: SchemaEntry) -> SchemaEntryView:
        """Возвращает typed view для одного :class:`SchemaEntry`."""
        return SchemaEntryView(entry)

    def snapshot_view(self, payload: dict[str, Any]) -> SnapshotView:
        """Возвращает typed view для snapshot payload (``to_snapshot`` output)."""
        return SnapshotView.from_json_dict(payload)

    def entry_from_dict(self, data: dict[str, Any]) -> SchemaEntry:
        """Восстанавливает :class:`SchemaEntry` из dict через TypeAdapter.

        Raises:
            pydantic.ValidationError: Если ``data`` не проходит validation.
            ValueError: Если ``kind`` отсутствует в :class:`SchemaKind`.

        """
        validated: dict[str, Any] = _DICT_ADAPTER.validate_python(data)
        kind_raw: Any = validated.get("kind")
        if kind_raw is None:
            raise ValueError("entry payload must contain 'kind' field")
        kind = SchemaKind(kind_raw)
        name_raw: Any = validated.get("name")
        if not isinstance(name_raw, str) or not name_raw:
            raise ValueError("entry payload must contain non-empty 'name' field")
        spec_schema = validated.get("spec_schema")
        output_schema = validated.get("output_schema")
        meta_raw = validated.get("meta") or {}
        if not isinstance(meta_raw, dict):
            raise ValueError("entry 'meta' must be a dict")
        return SchemaEntry(
            kind=kind,
            name=name_raw,
            spec_schema=spec_schema
            if isinstance(spec_schema, (dict, type(None)))
            else None,
            output_schema=(
                output_schema if isinstance(output_schema, (dict, type(None))) else None
            ),
            meta=meta_raw,
        )

    def validate_snapshot(self, data: dict[str, Any]) -> dict[str, Any]:
        """Валидирует snapshot payload через :class:`TypeAdapter`.

        Используется :meth:`ServiceSchemaRegistry.from_snapshot` как
        boundary-validator (typed entry-point для untyped dict).
        """
        validated: dict[str, Any] = _DICT_ADAPTER.validate_python(data)
        if validated.get("version") != CURRENT_SNAPSHOT_VERSION:
            raise ValueError(
                f"Unsupported snapshot version: {validated.get('version')!r}",
            )
        entries_raw: Any = validated.get("entries", [])
        if not isinstance(entries_raw, list):
            raise ValueError("snapshot 'entries' must be a list")
        # Strict-validate каждую запись (TypeAdapter list-of-dict).
        validated_entries: list[dict[str, Any]] = _LIST_ADAPTER.validate_python(
            entries_raw,
        )
        return {"version": validated["version"], "entries": validated_entries}


class SchemaEntryView:
    """Typed wrapper вокруг одного :class:`SchemaEntry`.

    Предоставляет :meth:`to_json_dict` для сериализации и
    :meth:`from_json_dict` (classmethod) для round-trip восстановления
    с :class:`pydantic.TypeAdapter` validation.
    """

    __slots__ = ("_entry",)

    def __init__(self, entry: SchemaEntry) -> None:
        """Сохраняет ссылку на оригинальный :class:`SchemaEntry` (не копирует)."""
        self._entry = entry

    @property
    def entry(self) -> SchemaEntry:
        """Оригинальный :class:`SchemaEntry` (read-only view)."""
        return self._entry

    def to_json_dict(self) -> dict[str, Any]:
        """Сериализует view в JSON-совместимый dict.

        Формат совместим с :meth:`ServiceSchemaRegistry.to_snapshot` —
        позволяет mixed use в callers.
        """
        return {
            "kind": self._entry.kind.value,
            "name": self._entry.name,
            "spec_schema": self._entry.spec_schema,
            "output_schema": self._entry.output_schema,
            "meta": dict(self._entry.meta),
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> SchemaEntryView:
        """Создаёт :class:`SchemaEntryView` из dict с TypeAdapter validation.

        Raises:
            pydantic.ValidationError: Если ``data`` не проходит validation.
            ValueError: Если ``kind`` невалиден или обязательные поля отсутствуют.

        """
        validated = _DICT_ADAPTER.validate_python(data)
        kind_raw: Any = validated.get("kind")
        if kind_raw is None:
            raise ValueError("entry payload must contain 'kind' field")
        kind = SchemaKind(kind_raw)
        name_raw: Any = validated.get("name")
        if not isinstance(name_raw, str) or not name_raw:
            raise ValueError("entry payload must contain non-empty 'name' field")
        entry = SchemaEntry(
            kind=kind,
            name=name_raw,
            spec_schema=validated.get("spec_schema"),
            output_schema=validated.get("output_schema"),
            meta=validated.get("meta") or {},
        )
        return cls(entry)


class SnapshotView:
    """Typed wrapper вокруг snapshot payload (result of :meth:`to_snapshot`).

    Round-trip: :meth:`to_json_dict` → JSON → :meth:`from_json_dict` (classmethod)
    с TypeAdapter validation. Используется на public boundary для safe
    persistence (snapshot to disk, передача через MQ и т.п.).
    """

    __slots__ = ("_payload",)

    def __init__(self, payload: dict[str, Any]) -> None:
        """Сохраняет уже-validated payload (используйте :meth:`from_json_dict`)."""
        self._payload = payload

    @property
    def version(self) -> str:
        r"""Версия snapshot формата (``\"2.0\"`` для текущего реестра)."""
        version_raw: Any = self._payload.get("version", "")
        return version_raw if isinstance(version_raw, str) else ""

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Список entries (defensive copy для иммутабельности snapshot view)."""
        return [dict(e) for e in self._payload.get("entries", [])]

    def to_json_dict(self) -> dict[str, Any]:
        """Возвращает snapshot payload (TypeAdapter-validated)."""
        return {"version": self.version, "entries": self.entries}

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> SnapshotView:
        """Создаёт :class:`SnapshotView` с :class:`TypeAdapter` validation.

        Raises:
            pydantic.ValidationError: Если ``data`` не проходит validation.
            ValueError: Если version невалиден или ``entries`` — не list.

        """
        validated = _DICT_ADAPTER.validate_python(data)
        version_raw: Any = validated.get("version")
        if version_raw != CURRENT_SNAPSHOT_VERSION:
            raise ValueError(f"Unsupported snapshot version: {version_raw!r}")
        entries_raw: Any = validated.get("entries", [])
        if not isinstance(entries_raw, list):
            raise ValueError("snapshot 'entries' must be a list")
        validated_entries: list[dict[str, Any]] = _LIST_ADAPTER.validate_python(
            entries_raw,
        )
        return cls({"version": version_raw, "entries": validated_entries})
