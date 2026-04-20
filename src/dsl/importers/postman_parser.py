"""Postman Collection → DSL Auto-Generator.

Принимает Postman Collection v2.1 (JSON) и генерирует DSL-роуты для
каждого запроса коллекции. Это эквивалент :class:`OpenAPIImporter`,
но для Postman-нотации — она часто поставляется вместе с внешними API.

Поддерживаются:

* folders (превращаются в префикс route_id);
* методы GET/POST/PUT/PATCH/DELETE;
* URL-параметры, query-params, headers, body (raw/json).

Actions (регистрируются в :mod:`app.dsl.commands.setup`):

* ``postman.import`` — импорт коллекции из dict или URL.
* ``postman.list_imported`` — список ранее импортированных коллекций.
* ``postman.preview`` — предпросмотр сгенерированного Python-кода без регистрации.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ("PostmanImporter", "ImportedPostmanRequest", "get_postman_importer")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImportedPostmanRequest:
    """Результат импорта одного запроса из Postman-коллекции."""

    route_id: str
    method: str
    url: str
    description: str
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, Any] = field(default_factory=dict)
    body: Any = None
    python_code: str = ""
    registered: bool = False


def _sanitize_id(name: str) -> str:
    """Преобразует произвольную строку в валидный route_id.

    Пример: ``"Get users by ID"`` → ``"get_users_by_id"``.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower())
    return cleaned.strip("_") or "unnamed"


class PostmanImporter:
    """Импортирует Postman-коллекцию v2.1 и генерирует DSL-роуты.

    Хранит результаты предыдущих импортов в ``_collections``
    (ключ — произвольный prefix из запроса пользователя).
    """

    def __init__(self) -> None:
        self._collections: dict[str, list[ImportedPostmanRequest]] = {}

    async def import_collection(
        self, collection: dict[str, Any] | str, *, prefix: str = "postman",
    ) -> dict[str, Any]:
        """Импортирует Postman-коллекцию.

        Args:
            collection: JSON коллекции (dict) или URL для загрузки.
            prefix: Префикс для ``route_id`` (``postman.<name>``).

        Returns:
            Отчёт со списком сгенерированных роутов.
        """
        data = await self._load(collection)
        info = data.get("info", {})
        collection_name = info.get("name", "collection")

        requests: list[ImportedPostmanRequest] = []
        items = data.get("item", [])
        self._walk_items(items, prefix, requests, path_prefix="")

        self._collections[prefix] = requests
        return {
            "collection": collection_name,
            "imported": len(requests),
            "routes": [r.route_id for r in requests],
        }

    def _walk_items(
        self,
        items: list[dict[str, Any]],
        prefix: str,
        out: list[ImportedPostmanRequest],
        path_prefix: str,
    ) -> None:
        """Рекурсивно обходит item-ы (с вложенными folder'ами)."""
        for item in items:
            if "item" in item:  # folder
                folder_name = _sanitize_id(item.get("name", ""))
                new_prefix = f"{path_prefix}.{folder_name}" if path_prefix else folder_name
                self._walk_items(item["item"], prefix, out, new_prefix)
                continue
            req = self._parse_request(item, prefix, path_prefix)
            if req:
                out.append(req)

    def _parse_request(
        self, item: dict[str, Any], prefix: str, folder_path: str,
    ) -> ImportedPostmanRequest | None:
        """Разбирает один request из Postman collection."""
        request = item.get("request")
        if not request:
            return None

        raw_name = item.get("name", "request")
        name = _sanitize_id(raw_name)
        route_id_parts = [prefix]
        if folder_path:
            route_id_parts.append(folder_path)
        route_id_parts.append(name)
        route_id = ".".join(route_id_parts)

        method = (request.get("method") or "GET").upper()
        url_obj = request.get("url", "")
        if isinstance(url_obj, dict):
            url = url_obj.get("raw", "")
            query_list = url_obj.get("query", []) or []
            query_params = {q["key"]: q.get("value", "") for q in query_list if q.get("key")}
        else:
            url = str(url_obj)
            query_params = {}

        headers_list = request.get("header", []) or []
        headers = {
            h["key"]: h.get("value", "")
            for h in headers_list
            if h.get("key") and not h.get("disabled")
        }

        body_obj = request.get("body", {})
        body = self._extract_body(body_obj) if body_obj else None

        code = self._generate_python(route_id, method, url, headers, query_params, body)

        return ImportedPostmanRequest(
            route_id=route_id,
            method=method,
            url=url,
            description=item.get("description") or raw_name,
            headers=headers,
            query_params=query_params,
            body=body,
            python_code=code,
        )

    @staticmethod
    def _extract_body(body_obj: dict[str, Any]) -> Any:
        """Извлекает тело запроса в зависимости от mode (raw/urlencoded/formdata)."""
        mode = body_obj.get("mode")
        if mode == "raw":
            return body_obj.get("raw")
        if mode == "urlencoded":
            return {p["key"]: p.get("value", "") for p in body_obj.get("urlencoded", [])}
        if mode == "formdata":
            return {p["key"]: p.get("value", "") for p in body_obj.get("formdata", [])}
        return None

    @staticmethod
    def _generate_python(
        route_id: str,
        method: str,
        url: str,
        headers: dict[str, str],
        query_params: dict[str, Any],
        body: Any,
    ) -> str:
        """Возвращает Python-сниппет для создания DSL-роута."""
        lines = [
            f'# Auto-generated from Postman для "{route_id}"',
            "from app.dsl.builder import RouteBuilder",
            "",
            "route = (",
            f'    RouteBuilder.from_("{route_id}", source="postman_import")',
            f'    .http_call("{url}", method="{method}",',
        ]
        if headers:
            lines.append(f"         headers={headers!r},")
        if query_params:
            lines.append(f"         query_params={query_params!r},")
        if body is not None:
            lines.append(f"         body={body!r},")
        lines.append("    )")
        lines.append("    .log()")
        lines.append("    .build()")
        lines.append(")")
        return "\n".join(lines)

    async def _load(self, spec: dict[str, Any] | str) -> dict[str, Any]:
        """Загружает коллекцию из dict или URL."""
        if isinstance(spec, dict):
            return spec
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(spec, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as exc:
            raise ValueError(f"Не удалось загрузить Postman-коллекцию {spec}: {exc}") from exc

    def list_imported(self) -> dict[str, list[str]]:
        """Возвращает карту ``prefix → [route_id, ...]``."""
        return {prefix: [r.route_id for r in reqs] for prefix, reqs in self._collections.items()}


_importer: PostmanImporter | None = None


def get_postman_importer() -> PostmanImporter:
    """Возвращает singleton-instance :class:`PostmanImporter`."""
    global _importer
    if _importer is None:
        _importer = PostmanImporter()
    return _importer
