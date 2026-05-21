"""HTTP-клиент для вызова FastAPI backend из Streamlit."""

from __future__ import annotations

import os
from typing import Any

import httpx

__all__ = ("APIClient", "get_api_client")

_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


class APIClient:
    """Синхронный HTTP-клиент к FastAPI."""

    def __init__(self, base_url: str = _BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        with httpx.Client(timeout=15) as client:
            response = client.request(method, self._url(path), **kwargs)
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return response.text

    def get_metrics(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/admin/metrics")

    def get_health(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/health/components")

    def get_routes(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/admin/routes")

    def get_orders(self, page: int = 1, size: int = 50) -> Any:
        return self._request(
            "GET", "/api/v1/orders/all/", params={"page": page, "size": size}
        )

    def create_order(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/orders/create/", json=data)

    def update_order(self, order_id: int, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/v1/orders/update/{order_id}", json=data)

    def delete_order(self, order_id: int) -> None:
        self._request("DELETE", f"/api/v1/orders/delete/{order_id}")

    def chat(self, message: str, session_id: str = "default") -> str:
        result = self._request(
            "POST",
            "/api/v1/ai/chat",
            json={"message": message, "session_id": session_id},
        )
        return (
            result.get("response", str(result))
            if isinstance(result, dict)
            else str(result)
        )

    def get_flags(self) -> list[dict[str, Any]]:
        try:
            return self._request("GET", "/api/v1/admin/feature-flags")
        except Exception:
            return []

    def toggle_flag(self, name: str, enabled: bool) -> bool:
        try:
            self._request(
                "POST",
                f"/api/v1/admin/feature-flags/{name}/toggle",
                json={"enabled": enabled},
            )
            return True
        except Exception:
            return False

    def get_config(self) -> dict[str, Any]:
        try:
            return self._request("GET", "/api/v1/admin/config")
        except Exception:
            return {}

    def get_trace_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        try:
            return self._request(
                "GET", "/api/v1/admin/trace-logs", params={"limit": limit}
            )
        except Exception:
            return []

    # -- Durable workflows (IL-WF1.5 admin API) -------------------------

    def list_workflows(
        self,
        *,
        status: str | None = None,
        workflow_name: str | None = None,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """GET /api/v1/admin/workflows — список instances с фильтрами."""
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if workflow_name:
            params["workflow_name"] = workflow_name
        if tenant_id:
            params["tenant_id"] = tenant_id
        try:
            result = self._request("GET", "/api/v1/admin/workflows", params=params)
            return result if isinstance(result, list) else []
        except Exception:
            return []

    def get_workflow(self, instance_id: str) -> dict[str, Any] | None:
        """GET /api/v1/admin/workflows/{id} — header + event log."""
        try:
            return self._request("GET", f"/api/v1/admin/workflows/{instance_id}")
        except Exception:
            return None

    def get_workflow_events(
        self, instance_id: str, *, after_seq: int = 0, limit: int = 200
    ) -> list[dict[str, Any]]:
        """GET /api/v1/admin/workflows/{id}/events — paginated event log."""
        try:
            result = self._request(
                "GET",
                f"/api/v1/admin/workflows/{instance_id}/events",
                params={"after_seq": after_seq, "limit": limit},
            )
            return result if isinstance(result, list) else []
        except Exception:
            return []

    def retry_workflow(self, instance_id: str) -> bool:
        """POST /{id}/retry — next_attempt_at=now."""
        try:
            self._request("POST", f"/api/v1/admin/workflows/{instance_id}/retry")
            return True
        except Exception:
            return False

    def cancel_workflow(self, instance_id: str, reason: str | None = None) -> bool:
        """POST /{id}/cancel — → compensate → cancelled."""
        try:
            self._request(
                "POST",
                f"/api/v1/admin/workflows/{instance_id}/cancel",
                json={"reason": reason} if reason else {},
            )
            return True
        except Exception:
            return False

    def resume_workflow(self, instance_id: str) -> bool:
        """POST /{id}/resume — для paused: немедленно execute."""
        try:
            self._request("POST", f"/api/v1/admin/workflows/{instance_id}/resume")
            return True
        except Exception:
            return False

    def trigger_workflow(
        self,
        workflow_name: str,
        payload: dict[str, Any],
        *,
        wait: bool = False,
        timeout_s: int = 30,
    ) -> dict[str, Any] | None:
        """POST /trigger/{name} — создать workflow instance."""
        try:
            return self._request(
                "POST",
                f"/api/v1/admin/workflows/trigger/{workflow_name}",
                json=payload,
                params={"wait": str(wait).lower(), "timeout_s": timeout_s},
            )
        except Exception:
            return None

    # ──────────── DSL Routes Store (Wave 3.8) ────────────

    def list_dsl_routes(self) -> list[str]:
        """GET /api/v1/admin/dsl-routes — список route_id из YAMLStore."""
        try:
            result = self._request("GET", "/api/v1/admin/dsl-routes")
            return result if isinstance(result, list) else []
        except Exception:
            return []

    def get_dsl_route(self, route_id: str) -> dict[str, Any] | None:
        """GET /api/v1/admin/dsl-routes/{id} — yaml + spec + python."""
        try:
            return self._request("GET", f"/api/v1/admin/dsl-routes/{route_id}")
        except Exception:
            return None

    def create_dsl_route(self, yaml_str: str) -> dict[str, Any]:
        """POST /api/v1/admin/dsl-routes — создать новый маршрут."""
        return self._request(
            "POST", "/api/v1/admin/dsl-routes", json={"yaml": yaml_str}
        )

    def update_dsl_route(self, route_id: str, yaml_str: str) -> dict[str, Any]:
        """PUT /api/v1/admin/dsl-routes/{id} — обновить маршрут."""
        return self._request(
            "PUT", f"/api/v1/admin/dsl-routes/{route_id}", json={"yaml": yaml_str}
        )

    def delete_dsl_route(self, route_id: str) -> bool:
        """DELETE /api/v1/admin/dsl-routes/{id} — удалить маршрут."""
        try:
            self._request("DELETE", f"/api/v1/admin/dsl-routes/{route_id}")
            return True
        except Exception:
            return False

    def validate_dsl_route(self, yaml_str: str) -> dict[str, Any]:
        """POST /api/v1/admin/dsl-routes/validate — валидация без записи."""
        try:
            return self._request(
                "POST", "/api/v1/admin/dsl-routes/validate", json={"yaml": yaml_str}
            )
        except Exception as exc:
            return {"valid": False, "error": str(exc)}

    def diff_dsl_route(self, route_id: str, yaml_str: str) -> dict[str, Any] | None:
        """POST /api/v1/admin/dsl-routes/{id}/diff — diff с переданным YAML."""
        try:
            return self._request(
                "POST",
                f"/api/v1/admin/dsl-routes/{route_id}/diff",
                json={"yaml": yaml_str},
            )
        except Exception:
            return None

    # ──────────── AI Feedback ────────────

    def list_feedback_pending(
        self, *, agent_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """GET /api/v1/ai/feedback/pending."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if agent_id:
            params["agent_id"] = agent_id
        return self._request("GET", "/api/v1/ai/feedback/pending", params=params)

    def list_feedback_labeled(
        self,
        *,
        label: str | None = None,
        agent_id: str | None = None,
        indexed_in_rag: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /api/v1/ai/feedback/labeled."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if label:
            params["label"] = label
        if agent_id:
            params["agent_id"] = agent_id
        if indexed_in_rag is not None:
            params["indexed_in_rag"] = str(indexed_in_rag).lower()
        return self._request("GET", "/api/v1/ai/feedback/labeled", params=params)

    def get_feedback_stats(self) -> dict[str, int]:
        """GET /api/v1/ai/feedback/stats."""
        return self._request("GET", "/api/v1/ai/feedback/stats")

    def label_feedback(
        self,
        doc_id: str,
        *,
        label: str,
        comment: str | None = None,
        operator_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/v1/ai/feedback/{id}/label."""
        payload: dict[str, Any] = {"label": label}
        if comment:
            payload["comment"] = comment
        if operator_id:
            payload["operator_id"] = operator_id
        return self._request(
            "POST", f"/api/v1/ai/feedback/{doc_id}/label", json=payload
        )

    def index_feedback_to_rag(
        self, *, agent_id: str | None = None, limit: int = 100
    ) -> dict[str, int]:
        """POST /api/v1/ai/feedback/index-to-rag."""
        payload: dict[str, Any] = {"limit": limit}
        if agent_id:
            payload["agent_id"] = agent_id
        return self._request("POST", "/api/v1/ai/feedback/index-to-rag", json=payload)

    # ──────────── V11 Plugin Marketplace (Sprint 3) ────────────

    def get_plugins_inventory(self) -> dict[str, Any]:
        """GET /api/v1/plugins/inventory.

        Returns:
            ``{"enabled": bool, "plugins": [...], "reason": str | None}``.
            Если loader выключен через feature-flag — ``enabled=False``
            и пустой массив.
        """
        try:
            return self._request("GET", "/api/v1/plugins/inventory")
        except Exception as exc:
            return {"enabled": False, "plugins": [], "reason": str(exc)}

    def get_routes_inventory(self) -> dict[str, Any]:
        """GET /api/v1/routes/inventory — V11 routes inventory."""
        try:
            return self._request("GET", "/api/v1/routes/inventory")
        except Exception as exc:
            return {"enabled": False, "routes": [], "reason": str(exc)}

    # ──────────── Sprint 14 plugin ecosystem ────────────

    def get_capability_catalog(self) -> dict[str, Any]:
        """Sprint 14 K1 W4 / pre-K5 — GET /api/v1/admin/capabilities."""
        try:
            return self._request("GET", "/api/v1/admin/capabilities")
        except Exception as exc:
            return {"vocabulary": [], "catalog": [], "error": str(exc)}

    def get_processor_catalog(
        self, query: str = "", namespace: str | None = None, limit: int = 25
    ) -> dict[str, Any]:
        """Sprint 14 K3 W1: GET /api/v1/dsl/processors/search."""
        params: dict[str, Any] = {"q": query, "limit": limit}
        if namespace:
            params["namespace"] = namespace
        try:
            return self._request("GET", "/api/v1/dsl/processors/search", params=params)
        except Exception as exc:
            return {"query": query, "items": [], "total": 0, "error": str(exc)}

    def get_audit_events(
        self, plugin: str | None = None, tenant: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Sprint 14 K1 W4: GET /api/v1/admin/audit/capability."""
        params: dict[str, Any] = {"limit": limit}
        if plugin:
            params["plugin"] = plugin
        if tenant:
            params["tenant"] = tenant
        try:
            response = self._request(
                "GET", "/api/v1/admin/audit/capability", params=params
            )
            if isinstance(response, list):
                return response
            return response.get("events", []) if isinstance(response, dict) else []
        except Exception:
            return []

    def get_dependency_graph(self) -> dict[str, Any]:
        """Sprint 14 K5 W3: GET /api/v1/admin/plugins/dependency-graph."""
        try:
            return self._request("GET", "/api/v1/admin/plugins/dependency-graph")
        except Exception as exc:
            return {"nodes": [], "edges": [], "error": str(exc)}

    def get_capability_graph(self) -> dict[str, Any]:
        """Sprint 14 K5 W5: GET /api/v1/admin/capabilities/graph."""
        try:
            return self._request("GET", "/api/v1/admin/capabilities/graph")
        except Exception as exc:
            return {"nodes": [], "edges": [], "error": str(exc)}

    def scaffold_plugin(
        self,
        name: str,
        *,
        description: str | None = None,
        capabilities: list[str] | None = None,
        features: list[str] | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Sprint 14 K5 W6: POST /api/v1/admin/plugins/scaffold."""
        body = {
            "name": name,
            "description": description,
            "capabilities": capabilities or [],
            "features": features or [],
            "dry_run": dry_run,
        }
        try:
            return self._request("POST", "/api/v1/admin/plugins/scaffold", json=body)
        except Exception as exc:
            return {"name": name, "created": False, "error": str(exc)}

    # ──────────── Sprint 5 K5 W1 — Workflow Step Logs ────────────

    def list_step_logs(
        self,
        workflow_name: str | None = None,
        tenant_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        status: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """GET /api/v1/admin/workflow/step-logs — список workflow step-логов.

        Args:
            workflow_name: Фильтр по имени workflow (substring match).
            tenant_id: Фильтр по tenant.
            date_from: Начало периода (ISO date YYYY-MM-DD).
            date_to: Конец периода (ISO date YYYY-MM-DD).
            status: Список статусов для фильтра (ok/fail/retry/timeout).
            limit: Максимум записей в ответе.

        Returns:
            Список step-логов (dict). При недоступности backend
            (К3 W11 ещё не готов) возвращает stub-данные с пометкой
            ``__stub__: True`` в каждой записи.
        """
        params: dict[str, Any] = {
            k: v
            for k, v in {
                "workflow_name": workflow_name,
                "tenant_id": tenant_id,
                "date_from": date_from,
                "date_to": date_to,
                "status": ",".join(status) if status else None,
                "limit": limit,
            }.items()
            if v is not None
        }
        try:
            result = self._request(
                "GET", "/api/v1/admin/workflow/step-logs", params=params
            )
            if isinstance(result, list):
                return result
            return []
        except Exception:  # noqa: BLE001
            # K3 W11 endpoint ещё не реализован — возвращаем stub.
            return _build_step_logs_stub(workflow_name=workflow_name, limit=limit)

    def get_step_detail(self, workflow_id: str) -> dict[str, Any]:
        """GET /api/v1/admin/workflow/step-logs/{workflow_id} — drill-down.

        Args:
            workflow_id: Идентификатор workflow для drill-down.

        Returns:
            Подробности workflow со списком всех steps. При недоступности
            backend возвращает stub-словарь с ``__stub__: True``.
        """
        try:
            result = self._request(
                "GET", f"/api/v1/admin/workflow/step-logs/{workflow_id}"
            )
            if isinstance(result, dict):
                return result
            return {}
        except Exception:  # noqa: BLE001
            return _build_step_detail_stub(workflow_id)


def _build_step_logs_stub(
    *, workflow_name: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Сформировать stub-данные при недоступности K3 W11 endpoint.

    Args:
        workflow_name: Если задано — используется в stub-записях.
        limit: Сколько stub-записей вернуть (минимум 3, максимум limit).

    Returns:
        Список stub-словарей с ключом ``__stub__=True`` для индикации в UI.
    """
    base_name = workflow_name or "credit_assessment"
    statuses = ("ok", "ok", "fail", "ok", "retry")
    rows: list[dict[str, Any]] = []
    count = max(3, min(limit, 5))
    for idx in range(count):
        rows.append(
            {
                "workflow_id": f"wf-stub-{idx:03d}",
                "workflow_name": base_name,
                "step_name": f"step_{idx}",
                "status": statuses[idx % len(statuses)],
                "duration_ms": 100 + idx * 50,
                "tenant_id": "stub-tenant",
                "ts": "2026-05-14T00:00:00Z",
                "__stub__": True,
            }
        )
    return rows


def _build_step_detail_stub(workflow_id: str) -> dict[str, Any]:
    """Stub для get_step_detail при недоступности backend."""
    return {
        "workflow_id": workflow_id,
        "status": "stub",
        "steps": [
            {"name": "step_0", "status": "ok", "duration_ms": 120},
            {"name": "step_1", "status": "ok", "duration_ms": 250},
        ],
        "__stub__": True,
    }


def get_api_client() -> APIClient:
    return APIClient()
