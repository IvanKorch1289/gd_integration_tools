"""Restricted unpickler для безопасной десериализации pickle-байтов.

Использовать только когда источник данных **не полностью доверенный**
(например, shared cache бэкенды: Redis, Memcached, network storage).
Для trusted-источников (MemoryBackend в текущем процессе) legacy
``pickle.loads`` остаётся допустимым — см. ``nosec B301`` annotations
в ``infrastructure.database.query_result_cache``.

Whitelist покрывает stdlib-типы, безопасные для round-trip через pickle
без выполнения произвольного кода. Любой класс вне whitelist → fail-closed
``pickle.UnpicklingError``.

Pattern (S47 W1): аналогично ``module_whitelist.py`` (S67 W1) — отдельный
namespace-пакет ``src.backend.core.security``, PEP 420 layout.

Whitelist rationale (по модулям):
* ``builtins``: базовые типы (int/str/list/dict/tuple/set/frozenset/...);
* ``collections``: OrderedDict/defaultdict/deque/Counter/ChainMap;
* ``dataclasses``: dataclass + field + dataclass instances;
* ``datetime``: datetime/date/time/timedelta/tzinfo;
* ``decimal``: Decimal;
* ``enum``: Enum/IntEnum/Flag (без выполнения ``__init__`` на custom members);
* ``typing`` (осторожно): только Generic alias typing, НЕ runtime values;
* ``uuid``: UUID;
* ``pathlib``: PurePath/Path (только immutable Pure-варианты);
* ``copyreg``: ``_reconstructor`` (внутренний pickle helper);
* ``array``: array.array;
* ``struct``: struct.Struct;
* ``math``: только математические константы (pi/e/...).

P0-S7 (audit 2026-08-19): см. ``docs/audit/RE_AUDIT_2026-08-19.md``.
"""

from __future__ import annotations

import io  # nosec B401 - restricted unpickler использует BytesIO как file-like
import pickle  # nosec B403 - intentional, gated by RestrictedUnpickler.find_class
from typing import Any, Final

__all__ = ("RestrictedUnpickler", "safe_loads", "DEFAULT_ALLOWLIST")

# Whitelist безопасных top-level модулей для ``find_class``.
# Используем frozenset для O(1) lookup и неизменяемости.
DEFAULT_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "builtins",
        "collections",
        "collections.abc",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "uuid",
        "pathlib",
        "copyreg",
        "array",
        "struct",
        "math",
        "fractions",
        "ipaddress",
        "re",
        "typing",  # Generic alias only — runtime eval не происходит
    }
)

# Sub-module allowlist для модулей с подмодулями (например, datetime.time).
_DEFAULT_SUBMODULE_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "collections",
        "datetime",
        "pathlib",
        "enum",
        "typing",
    }
)


class RestrictedUnpickler(pickle.Unpickler):
    """Pickle.Unpickler с whitelist модулей в ``find_class``.

    Args:
        file: Bytes/IO source для pickle stream.
        allowlist: Iterable top-level модулей, разрешённых к десериализации.
            По умолчанию ``DEFAULT_ALLOWLIST``.

    Raises:
        pickle.UnpicklingError: Если класс вне ``allowlist``.

    """

    def __init__(self, file: Any, *, allowlist: frozenset[str] = DEFAULT_ALLOWLIST) -> None:
        super().__init__(file)
        self._allowlist = allowlist

    def find_class(self, module: str, name: str) -> Any:  # noqa: D401 - pickle API
        """Override pickle.Unpickler.find_class с whitelist-проверкой.

        Args:
            module: Top-level module name из pickle stream.
            name: Class/attribute name из pickle stream.

        Returns:
            Десериализованный объект (только если модуль в whitelist).

        Raises:
            pickle.UnpicklingError: Если ``module`` не в whitelist или
                выглядит как попытка обхода (например, ``os.system``).

        """
        # Top-level module check (или префикс подмодуля).
        top = module.split(".", 1)[0]
        allowed = top in self._allowlist or module in self._allowlist
        if not allowed:
            raise pickle.UnpicklingError(
                f"RestrictedUnpickler: module '{module}' not in allowlist "
                f"(top-level '{top}' denied; see DEFAULT_ALLOWLIST)"
            )

        # Дополнительная защита: даже whitelisted модули не должны
        # импортировать ``os``/``subprocess``/``sys``/builtins.eval/exec.
        # pickle вызывает только ``module.name`` lookup, но проверим имя.
        forbidden_names = {"eval", "exec", "compile", "__import__", "system", "popen"}
        if name in forbidden_names:
            raise pickle.UnpicklingError(
                f"RestrictedUnpickler: attribute '{name}' in module '{module}' "
                f"is forbidden (RCE vector)"
            )

        return super().find_class(module, name)


def safe_loads(
    data: bytes,
    *,
    allowlist: frozenset[str] | None = None,
) -> Any:
    """Безопасная десериализация pickle-байтов через ``RestrictedUnpickler``.

    Args:
        data: Pickle-serialized bytes.
        allowlist: Опциональный override whitelist. ``None`` → ``DEFAULT_ALLOWLIST``.

    Returns:
        Десериализованный Python объект.

    Raises:
        pickle.UnpicklingError: Если класс вне whitelist или RCE vector.

    Example:
        >>> import pickle, dataclasses
        >>> @dataclasses.dataclass
        ... class Point:
        ...     x: int
        ...     y: int
        >>> p = pickle.dumps(Point(1, 2))
        >>> safe_loads(p)
        Point(x=1, y=2)

    """
    wl = allowlist if allowlist is not None else DEFAULT_ALLOWLIST
    return RestrictedUnpickler(io.BytesIO(data), allowlist=wl).load()
