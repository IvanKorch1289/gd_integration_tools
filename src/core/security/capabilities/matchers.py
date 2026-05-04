"""ADR-044 — ScopeMatcher-strategy для разных типов ресурсов.

CapabilityGate делегирует резолвинг scope соответствующему matcher'у:

* ``db.*`` → :class:`ExactAliasMatcher` (DSN-aliases — точное совпадение).
* ``net.*`` / ``mq.*`` / ``workflow.*`` →
  :class:`SegmentedGlobMatcher` с sep=``.`` (host/topic/workflow_id —
  сегменты разделяются точкой).
* ``fs.*`` → :class:`SegmentedGlobMatcher` с sep=``/`` (path-glob).
* ``cache.*`` → :class:`SegmentedGlobMatcher` с sep=``:`` (namespace
  через двоеточие).
* ``llm.*`` → :class:`SegmentedGlobMatcher` с sep=``/`` (provider/model).
* ``secrets.*`` → :class:`URISchemeMatcher` (учёт URI-префиксов).

В сегментной семантике ``*`` совпадает ровно с одним непустым
сегментом, ``**`` — с любым числом (в т.ч. 0).
"""

from __future__ import annotations

import re
from typing import Final, Protocol, runtime_checkable

__all__ = (
    "ExactAliasMatcher",
    "GlobScopeMatcher",
    "ScopeMatcher",
    "SegmentedGlobMatcher",
    "URISchemeMatcher",
)


@runtime_checkable
class ScopeMatcher(Protocol):
    """Strategy-интерфейс для резолвинга scope."""

    def match(self, requested: str, declared: str) -> bool:
        """Покрывает ли ``declared`` запрошенный ``requested``."""
        ...


class ExactAliasMatcher:
    """Точное совпадение alias'ов (DSN-имена БД)."""

    def match(self, requested: str, declared: str) -> bool:
        """Возвращает ``True`` только при полном равенстве строк."""
        return requested == declared


class SegmentedGlobMatcher:
    """Glob с явным разделителем сегментов (``.``, ``/``, ``:``).

    * ``*`` совпадает ровно с одним непустым сегментом (``[^sep]+``).
    * ``**`` совпадает с любым числом сегментов (``.*``), включая ноль.
    * Прочие символы — литералы, экранируются.

    Args:
        sep: Один символ-разделитель (``"."``, ``"/"``, ``":"``).
    """

    def __init__(self, sep: str) -> None:
        if len(sep) != 1:
            raise ValueError(f"sep must be exactly one char, got {sep!r}")
        self._sep = sep

    def match(self, requested: str, declared: str) -> bool:
        """Сматчить ``requested`` против сегментного glob'а ``declared``."""
        pattern = self._compile(declared)
        return pattern.fullmatch(requested) is not None

    def _compile(self, declared: str) -> re.Pattern[str]:
        """Транслирует glob в anchored regex.

        Особый случай: ``<sep>**`` (например, ``credit.events.**``)
        считается «опциональным разделителем + произвольный suffix»,
        чтобы покрыть и ``credit.events``, и ``credit.events.x.y``.
        Это соответствует семантике «всё начиная отсюда» из ADR-044.
        """
        sep_re = re.escape(self._sep)
        result: list[str] = []
        i = 0
        n = len(declared)
        while i < n:
            ch = declared[i]
            if ch == "*":
                if i + 1 < n and declared[i + 1] == "*":
                    # Если предыдущий output — это sep, делаем его опциональным
                    # вместе с `**` суффиксом.
                    if result and result[-1] == sep_re:
                        result.pop()
                        result.append(f"(?:{sep_re}.*)?")
                    else:
                        result.append(".*")
                    i += 2
                else:
                    # `*` — один сегмент: ≥1 символ, не равный sep
                    result.append(f"[^{sep_re}]+")
                    i += 1
            else:
                result.append(re.escape(ch))
                i += 1
        return re.compile("".join(result))


class GlobScopeMatcher(SegmentedGlobMatcher):
    """fnmatch-совместимый glob с sep=``.`` (по умолчанию).

    Для совместимости с типичным topic/host-glob, где сегменты
    разделяются точкой. Эквивалентен :class:`SegmentedGlobMatcher`
    с ``sep="."``.
    """

    def __init__(self) -> None:
        super().__init__(sep=".")


class URISchemeMatcher:
    """Match с учётом URI-схемы (``vault://``, ``env://``, ``kms://``).

    Если declared содержит схему (например, ``vault://credit/*``), то
    requested обязан иметь ту же схему — пути сматчиваются glob'ом
    по сегментам ``/`` после двоеточия.
    """

    _SCHEMES: Final[tuple[str, ...]] = ("vault://", "env://", "kms://")
    _PATH_GLOB: Final[SegmentedGlobMatcher] = SegmentedGlobMatcher(sep="/")

    def match(self, requested: str, declared: str) -> bool:
        """Сматчить с учётом схемы."""
        declared_scheme = self._extract_scheme(declared)
        requested_scheme = self._extract_scheme(requested)
        if declared_scheme != requested_scheme:
            return False
        if declared_scheme is None:
            # Без схемы — простое равенство (legacy alias-семантика).
            return requested == declared
        # Сматчиваем path-часть после схемы.
        declared_path = declared[len(declared_scheme) :]
        requested_path = requested[len(requested_scheme) :]
        return self._PATH_GLOB.match(requested_path, declared_path)

    @classmethod
    def _extract_scheme(cls, value: str) -> str | None:
        """Возвращает префикс из :data:`_SCHEMES` или ``None``."""
        for scheme in cls._SCHEMES:
            if value.startswith(scheme):
                return scheme
        return None
