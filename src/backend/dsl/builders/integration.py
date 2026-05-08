"""Integration / Transport / Storage / Security / Banking миксин для RouteBuilder.

Группа: entity_create/get/update/delete/list + crud_create/read/update/delete/list
(alias) + dispatch_action / invoke / proxy / forward_to / redirect /
expose_proxy / http_call / db_query / db_query_external / notify / email /
publish_event / sink-publish / read_file / write_file / read_s3 / write_s3 /
file_move / timer / poll / auth (require_*, jwt_*, webhook_*) / scan_file +
NEW invoke_workflow / call_function / get_setting / validate_response.

Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations


class IntegrationMixin:
    """Поведенческий миксин integration/transport/storage/security для ``RouteBuilder``."""

    __slots__ = ()  # type: ignore[var-annotated]
