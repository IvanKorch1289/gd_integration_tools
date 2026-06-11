from __future__ import annotations
"""S66 W2 — orchestrator.py part of setup.py decomp.

main register_action_handlers() orchestrator.

Functions: register_action_handlers.
"""

from collections.abc import Callable

from src.backend.dsl.commands.registry import ActionHandlerSpec, action_handler_registry

from src.backend.dsl.commands.setup.registers_domains import _register_orders  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_domains import _register_files  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_domains import _register_skb_api  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_domains import _register_dadata  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_domains import _register_tech  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_domains import _register_admin  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_domains import _register_servicedsl_auto_register  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_integrations import _register_ai  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_integrations import _register_analytics_clickhouse  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_integrations import _register_search_elasticsearch  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_integrations import _register_notebooks_wave_9_1  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_integrations import _register_rag_vector_db_llm  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_integrations import _register_agent_memory  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_integrations import _register_web_search_perplexity_tavily  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_integrations import _register_anomaly_detection  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_workflow import _register_webhook_scheduler  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_workflow import _register_web_automation_multi_protocol  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_workflow import _register_data_export_excel_csv_pdf  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_workflow import _register_notifications_email_express_webhook_telegram  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_workflow import _register_message_replay  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_workflow import _register_webhook_relay  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_workflow import _register_scheduled_reports  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_workflow import _register_data_quality  # S66 W2: orchestrator cross-import
from src.backend.dsl.commands.setup.registers_workflow import _register_importgateway_w24  # S66 W2: orchestrator cross-import





def register_action_handlers() -> None:
    """Регистрирует все action-handlers приложения.

    Функция идемпотентна — вызывается на startup приложения.
    Per-service registration делегировано в ``_register_xxx()`` helpers (S53 W3 extraction).
    Каждый helper делает свои own lazy imports (preserve original pattern).
    """
    _register_orders()
    _register_files()
    _register_skb_api()
    _register_dadata()
    _register_tech()
    _register_ai()
    _register_admin()
    _register_analytics_clickhouse()
    _register_search_elasticsearch()
    _register_notebooks_wave_9_1()
    _register_rag_vector_db_llm()
    _register_agent_memory()
    _register_webhook_scheduler()
    _register_web_automation_multi_protocol()
    _register_web_search_perplexity_tavily()
    _register_data_export_excel_csv_pdf()
    _register_notifications_email_express_webhook_telegram()
    _register_anomaly_detection()
    _register_message_replay()
    _register_webhook_relay()
    _register_data_quality()
    _register_importgateway_w24()
    _register_scheduled_reports()
    _register_servicedsl_auto_register()



