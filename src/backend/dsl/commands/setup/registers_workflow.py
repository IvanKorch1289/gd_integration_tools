from __future__ import annotations

"""S66 W2 — registers_workflow.py part of setup.py decomp.

workflow/notification registrations (webhook, replay, scheduled, etc.).

Functions: _register_webhook_scheduler, _register_web_automation_multi_protocol, _register_data_export_excel_csv_pdf, _register_notifications_email_express_webhook_telegram, _register_message_replay, _register_webhook_relay, _register_scheduled_reports, _register_data_quality, _register_importgateway_w24.
"""


from src.backend.dsl.commands.registry import ActionHandlerSpec, action_handler_registry


def _register_webhook_scheduler() -> None:

    from src.backend.services.ops.webhook_scheduler import get_webhook_scheduler

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="webhook.schedule",
                service_getter=get_webhook_scheduler,
                service_method="schedule",
            ),
            ActionHandlerSpec(
                action="webhook.cancel",
                service_getter=get_webhook_scheduler,
                service_method="cancel",
            ),
            ActionHandlerSpec(
                action="webhook.list_scheduled",
                service_getter=get_webhook_scheduler,
                service_method="list_scheduled",
            ),
            ActionHandlerSpec(
                action="webhook.execute",
                service_getter=get_webhook_scheduler,
                service_method="execute_webhook",
            ),
        ]
    )


def _register_web_automation_multi_protocol() -> None:

    from src.backend.services.io.web_automation import get_web_automation_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="web.navigate",
                service_getter=get_web_automation_service,
                service_method="navigate",
            ),
            ActionHandlerSpec(
                action="web.click",
                service_getter=get_web_automation_service,
                service_method="click",
            ),
            ActionHandlerSpec(
                action="web.fill_form",
                service_getter=get_web_automation_service,
                service_method="fill_form",
            ),
            ActionHandlerSpec(
                action="web.extract_text",
                service_getter=get_web_automation_service,
                service_method="extract_text",
            ),
            ActionHandlerSpec(
                action="web.extract_table",
                service_getter=get_web_automation_service,
                service_method="extract_table",
            ),
            ActionHandlerSpec(
                action="web.screenshot",
                service_getter=get_web_automation_service,
                service_method="screenshot",
            ),
            ActionHandlerSpec(
                action="web.run_scenario",
                service_getter=get_web_automation_service,
                service_method="run_scenario",
            ),
            ActionHandlerSpec(
                action="web.parse_page",
                service_getter=get_web_automation_service,
                service_method="parse_page",
            ),
            ActionHandlerSpec(
                action="web.monitor_changes",
                service_getter=get_web_automation_service,
                service_method="monitor_changes",
            ),
        ]
    )


def _register_data_export_excel_csv_pdf() -> None:

    from src.backend.services.io.export_service import get_export_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="export.to_csv",
                service_getter=get_export_service,
                service_method="to_csv",
            ),
            ActionHandlerSpec(
                action="export.to_excel",
                service_getter=get_export_service,
                service_method="to_excel",
            ),
            ActionHandlerSpec(
                action="export.to_pdf",
                service_getter=get_export_service,
                service_method="to_pdf",
            ),
        ]
    )


def _register_notifications_email_express_webhook_telegram() -> None:

    from src.backend.services.ops.notification_hub import get_notification_hub

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="notify.send",
                service_getter=get_notification_hub,
                service_method="send",
            ),
            ActionHandlerSpec(
                action="notify.email",
                service_getter=get_notification_hub,
                service_method="email",
            ),
            ActionHandlerSpec(
                action="notify.express",
                service_getter=get_notification_hub,
                service_method="express",
            ),
            ActionHandlerSpec(
                action="notify.express_broadcast",
                service_getter=get_notification_hub,
                service_method="express_broadcast",
            ),
            ActionHandlerSpec(
                action="notify.express_create_chat",
                service_getter=get_notification_hub,
                service_method="express_create_chat",
            ),
            ActionHandlerSpec(
                action="notify.express_event",
                service_getter=get_notification_hub,
                service_method="express_event",
            ),
            ActionHandlerSpec(
                action="notify.webhook",
                service_getter=get_notification_hub,
                service_method="webhook",
            ),
            ActionHandlerSpec(
                action="notify.telegram",
                service_getter=get_notification_hub,
                service_method="telegram",
            ),
            ActionHandlerSpec(
                action="notify.broadcast",
                service_getter=get_notification_hub,
                service_method="broadcast",
            ),
        ]
    )


def _register_message_replay() -> None:

    from src.backend.services.ops.message_replay import get_replay_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="replay.list",
                service_getter=get_replay_service,
                service_method="list_messages",
            ),
            ActionHandlerSpec(
                action="replay.one",
                service_getter=get_replay_service,
                service_method="replay_one",
            ),
            ActionHandlerSpec(
                action="replay.bulk",
                service_getter=get_replay_service,
                service_method="replay_bulk",
            ),
            ActionHandlerSpec(
                action="replay.stats",
                service_getter=get_replay_service,
                service_method="stats",
            ),
        ]
    )


def _register_webhook_relay() -> None:

    from src.backend.entrypoints.webhook.transformer import get_webhook_relay

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="webhook.relay",
                service_getter=get_webhook_relay,
                service_method="relay",
            ),
            ActionHandlerSpec(
                action="webhook.transform",
                service_getter=get_webhook_relay,
                service_method="transform",
            ),
            ActionHandlerSpec(
                action="webhook.dlq_list",
                service_getter=get_webhook_relay,
                service_method="dlq_list",
            ),
            ActionHandlerSpec(
                action="webhook.dlq_retry",
                service_getter=get_webhook_relay,
                service_method="dlq_retry",
            ),
        ]
    )


def _register_data_quality() -> None:

    from src.backend.services.ops.data_quality import get_dq_monitor

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="dq.check", service_getter=get_dq_monitor, service_method="check"
            ),
            ActionHandlerSpec(
                action="dq.schema_infer",
                service_getter=get_dq_monitor,
                service_method="schema_infer",
            ),
            ActionHandlerSpec(
                action="dq.stats", service_getter=get_dq_monitor, service_method="stats"
            ),
        ]
    )


def _register_importgateway_w24() -> None:

    from src.backend.services.integrations import get_import_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="connector.import",
                service_getter=get_import_service,
                service_method="import_action",
            ),
            ActionHandlerSpec(
                action="connector.list_imported",
                service_getter=get_import_service,
                service_method="list_imported",
            ),
        ]
    )


def _register_scheduled_reports() -> None:

    from src.backend.services.ops.scheduled_reports import get_reports_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="reports.schedule",
                service_getter=get_reports_service,
                service_method="schedule",
            ),
            ActionHandlerSpec(
                action="reports.list",
                service_getter=get_reports_service,
                service_method="list_reports",
            ),
            ActionHandlerSpec(
                action="reports.run_now",
                service_getter=get_reports_service,
                service_method="run_now",
            ),
            ActionHandlerSpec(
                action="reports.history",
                service_getter=get_reports_service,
                service_method="history",
            ),
        ]
    )
