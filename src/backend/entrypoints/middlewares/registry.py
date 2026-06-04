"""MiddlewareRegistry — единая точка регистрации ASGI middleware (S17 ADR-NEW-2).

Назначение
----------
До S17 встроенные middleware регистрировались жёстким списком в
:func:`setup_middlewares.setup_middlewares`: ``app.add_middleware(...)``
вызывался последовательно по 25+ позициям, плагины не имели легитимного
способа подвесить свой middleware в нужный слой.

ADR-NEW-2 (Sprint 17 K3 W2) вводит реестр, который:

* регистрирует **built-in** middleware с явным ``order`` (слой 1: 0-249,
  слой 2: 250-499, слой 3: 500-749, слой 4: 750-999);
* принимает **plugin.toml ``[[middleware]]``** секции для регистрации
  middleware из расширений;
* принимает **entry-points** ``gd_integration_tools.middleware_hooks``
  для регистрации из установленных пакетов без plugin.toml;
* поддерживает per-route override (``enabled_routes`` / ``disabled_routes``)
  для middleware, ограниченных подмножеством путей;
* рендерит дерево слоёв для ``make middleware-tree``.

Совместимость
-------------
Внешний API ``setup_middlewares(app)`` сохранён: внутри он вызывает
:class:`MiddlewareRegistry`. Порядок применения совпадает со старым
жёстким списком (за счёт явных ``order`` для built-in).

Pydantic Settings или вычисление chain'а на старте знакомо приложениям
FastAPI/Starlette; здесь регистрируется отдельный chain — order сохраняет
LIFO-поведение Starlette (``add_middleware`` оборачивает наружу),
поэтому ``apply_to_app`` итерируется по spec'ам в порядке возрастания
``order`` (низкий order → наружный middleware → первая обработка).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib import import_module
from threading import Lock
from typing import Any

__all__ = ("MiddlewareRegistry", "MiddlewareSpec", "default_registry")


@dataclass(frozen=True, slots=True)
class MiddlewareSpec:
    """Декларация одного middleware в реестре.

    Атрибуты:
        name: Уникальный идентификатор (``snake_case``). Используется
            как ключ дедупликации: повторный register с тем же name
            заменяет предыдущий spec.
        middleware_cls: ASGI middleware-класс (Starlette/FastAPI совместимый).
        options: Параметры конструктора middleware (``**options`` идут
            в ``app.add_middleware``).
        order: Целочисленный порядок слоя (низкий = наружный).
            * 0–249 — Layer 1: early exit (CORS, TrustedHost, blocked, IPs);
            * 250–499 — Layer 2: request management (ID, tenant, context, idempotency);
            * 500–749 — Layer 3: body/auth (cache, compression, masking, auth);
            * 750–999 — Layer 4: logging/metrics (audit, OTel, Prometheus).
        enabled_routes: Optional shell-glob паттерны путей, для которых
            middleware **должен** применяться (per-route gate). Пусто →
            middleware применяется ко всем путям.
        disabled_routes: Аналогично, но для исключения. Имеет приоритет
            над ``enabled_routes`` при коллизии.
        source: Откуда зарегистрирован (``builtin`` / ``plugin:<name>`` /
            ``entry_point:<dist>``). Используется только для render_tree.
    """

    name: str
    middleware_cls: type
    options: Mapping[str, Any] = field(default_factory=dict)
    order: int = 500
    enabled_routes: tuple[str, ...] = ()
    disabled_routes: tuple[str, ...] = ()
    source: str = "builtin"


class MiddlewareRegistry:
    """Реестр middleware с тремя источниками регистрации.

    Регистрация thread-safe (``threading.Lock``), потому что entry-points
    и plugin.toml могут грузиться из разных startup-веток (lifespan +
    plugin loader). Re-entrancy не используется — каждый публичный метод
    делает один lock-acquire без вложенных вызовов другого, поэтому
    обычный :class:`Lock` достаточен (V22 §5: избегаем RLock в sync-only
    регистрациях).
    """

    def __init__(self) -> None:
        self._specs: dict[str, MiddlewareSpec] = {}
        self._lock = Lock()

    # --- Регистрация ------------------------------------------------- #
    def register_builtin(
        self,
        name: str,
        middleware_cls: type,
        options: Mapping[str, Any] | None = None,
        *,
        order: int,
        enabled_routes: Iterable[str] = (),
        disabled_routes: Iterable[str] = (),
    ) -> None:
        """Регистрирует built-in middleware с явным ``order``.

        Используется ``setup_middlewares`` для переноса жёсткого списка
        в реестр. Повторный вызов с тем же ``name`` заменяет spec.
        """
        spec = MiddlewareSpec(
            name=name,
            middleware_cls=middleware_cls,
            options=dict(options or {}),
            order=order,
            enabled_routes=tuple(enabled_routes),
            disabled_routes=tuple(disabled_routes),
            source="builtin",
        )
        with self._lock:
            self._specs[name] = spec

    def register_from_plugin(self, plugin_name: str, spec: MiddlewareSpec) -> None:
        """Регистрирует middleware, заявленный плагином (``plugin.toml``).

        ``spec`` уже содержит ``middleware_cls`` (загруженный через
        ``importlib`` из строки ``module:Class`` в TOML).
        """
        marked = MiddlewareSpec(
            name=spec.name,
            middleware_cls=spec.middleware_cls,
            options=spec.options,
            order=spec.order,
            enabled_routes=spec.enabled_routes,
            disabled_routes=spec.disabled_routes,
            source=f"plugin:{plugin_name}",
        )
        with self._lock:
            self._specs[spec.name] = marked

    def register_from_toml(
        self, plugin_name: str, toml_section: Iterable[Mapping[str, Any]]
    ) -> None:
        """Распарсить ``plugin.toml`` секцию ``[[middleware]]`` и зарегистрировать.

        Поддерживаемые ключи:

        * ``name`` (str, обязателен) — уникальный идентификатор;
        * ``module`` (str, обязателен) — ``package.module:ClassName``;
        * ``order`` (int, default 500) — слой;
        * ``options`` (table, default {}) — kwargs конструктора;
        * ``enabled_routes`` (array<str>);
        * ``disabled_routes`` (array<str>).

        Невалидные записи (без ``name`` или ``module``, ошибка импорта)
        пропускаются с ``ValueError``-исключением, чтобы plugin loader
        мог сообщить причину пользователю.
        """
        for entry in toml_section:
            name = entry.get("name")
            module_ref = entry.get("module")
            if not name or not module_ref:
                raise ValueError(
                    f"plugin '{plugin_name}': [[middleware]] требует "
                    "name + module (получено: " + str(entry) + ")"
                )
            mod_name, _, cls_name = module_ref.partition(":")
            if not mod_name or not cls_name:
                raise ValueError(
                    f"plugin '{plugin_name}': module='{module_ref}' "
                    "должен иметь форму 'package.module:ClassName'"
                )
            try:
                mod = import_module(mod_name)
                cls = getattr(mod, cls_name)
            except (ImportError, AttributeError) as exc:
                raise ValueError(
                    f"plugin '{plugin_name}': не удалось импортировать "
                    f"{module_ref}: {exc}"
                ) from exc
            spec = MiddlewareSpec(
                name=name,
                middleware_cls=cls,
                options=entry.get("options") or {},
                order=int(entry.get("order", 500)),
                enabled_routes=tuple(entry.get("enabled_routes") or ()),
                disabled_routes=tuple(entry.get("disabled_routes") or ()),
                source=f"plugin:{plugin_name}",
            )
            with self._lock:
                self._specs[name] = spec

    def register_from_entry_points(
        self, group: str = "gd_integration_tools.middleware_hooks"
    ) -> None:
        """Подобрать middleware через entry-points группу.

        Каждая entry-point должна возвращать (или быть классом) ASGI
        middleware-класс. Имя entry-point используется как ``name``,
        ``order`` фиксируется на 500 (по умолчанию). Distribution-имя
        записывается в ``source``.
        """
        from importlib.metadata import entry_points

        eps = entry_points(group=group)
        for ep in eps:
            try:
                target = ep.load()
            except Exception as exc:
                raise ValueError(
                    f"entry_point '{group}:{ep.name}' load failed: {exc}"
                ) from exc
            if not isinstance(target, type):
                raise ValueError(
                    f"entry_point '{group}:{ep.name}' должен указывать на класс, "
                    f"получено: {type(target).__name__}"
                )
            dist = getattr(ep, "dist", None)
            dist_name = getattr(dist, "name", "unknown") if dist else "unknown"
            spec = MiddlewareSpec(
                name=ep.name,
                middleware_cls=target,
                order=500,
                source=f"entry_point:{dist_name}",
            )
            with self._lock:
                self._specs[ep.name] = spec

    # --- Применение -------------------------------------------------- #
    def apply_to_app(
        self,
        app: Any,
        *,
        route_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[str, ...]:
        """Применить накопленные spec'и к FastAPI/Starlette app.

        Аргументы:
            app: Экземпляр FastAPI/Starlette.
            route_overrides: Optional ``{name: {"enabled": bool, "options": {...}}}``
                для override per-route из ``route.toml``. Если ``enabled=False``,
                middleware пропускается.

        Возвращает:
            Кортеж имён применённых middleware (в порядке возрастания order).
        """
        overrides = route_overrides or {}
        with self._lock:
            ordered = sorted(self._specs.values(), key=lambda s: (s.order, s.name))
        applied: list[str] = []
        for spec in ordered:
            override = overrides.get(spec.name, {})
            if override.get("enabled") is False:
                continue
            options = {**spec.options, **(override.get("options") or {})}
            app.add_middleware(spec.middleware_cls, **options)
            applied.append(spec.name)
        return tuple(applied)

    # --- Render для make middleware-tree ----------------------------- #
    def render_tree(self) -> str:
        """Вернуть дерево middleware по слоям для CLI ``make middleware-tree``.

        Формат::

            Layer 1 (early exit, 0-249):
              [001] cors                 (builtin) src=fastapi.middleware.cors:CORSMiddleware
            Layer 2 (request mgmt, 250-499):
              [260] request_id           (builtin) src=...
            ...
        """
        layers: dict[str, list[MiddlewareSpec]] = {
            "Layer 1 (early exit, 0-249)": [],
            "Layer 2 (request mgmt, 250-499)": [],
            "Layer 3 (body/auth, 500-749)": [],
            "Layer 4 (logging/metrics, 750-999)": [],
            "Layer 5 (out of range, 1000+)": [],
        }
        with self._lock:
            specs = sorted(self._specs.values(), key=lambda s: (s.order, s.name))
        for spec in specs:
            key = _layer_for(spec.order)
            layers[key].append(spec)
        lines: list[str] = []
        for layer, items in layers.items():
            if not items:
                continue
            lines.append(layer + ":")
            for spec in items:
                mod = spec.middleware_cls.__module__
                cls = spec.middleware_cls.__name__
                lines.append(
                    f"  [{spec.order:03d}] {spec.name:<28} "
                    f"({spec.source}) src={mod}:{cls}"
                )
        return "\n".join(lines)

    def specs(self) -> tuple[MiddlewareSpec, ...]:
        """Вернуть упорядоченный snapshot всех зарегистрированных spec'ов."""
        with self._lock:
            return tuple(sorted(self._specs.values(), key=lambda s: (s.order, s.name)))

    def clear(self) -> None:
        """Удалить все зарегистрированные spec'и (для тестов)."""
        with self._lock:
            self._specs.clear()


def _layer_for(order: int) -> str:
    """Сопоставить ``order`` имени слоя для ``render_tree``."""
    if order < 250:
        return "Layer 1 (early exit, 0-249)"
    if order < 500:
        return "Layer 2 (request mgmt, 250-499)"
    if order < 750:
        return "Layer 3 (body/auth, 500-749)"
    if order < 1000:
        return "Layer 4 (logging/metrics, 750-999)"
    return "Layer 5 (out of range, 1000+)"


default_registry: MiddlewareRegistry = MiddlewareRegistry()
