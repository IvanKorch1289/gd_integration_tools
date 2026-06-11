"""Credit Check Demo — Python fluent builder (S27 W3/W4 PoC).

Этот файл демонстрирует использование AgentDSLMixin fluent API
для построения credit_check route программно.
"""

from __future__ import annotations

from src.backend.dsl.builders.base import RouteBuilder


def build_credit_check_route() -> None:
    """Строит credit_check route через fluent Python API.

    Использует все 11 fluent методов AgentDSLMixin:
    - ai_memory_recall / ai_memory_store
    - pii_mask / pii_unmask
    - guardrails_apply
    - agent_run / agent_branch / agent_loop / agent_parallel
    - skill_invoke / ai_invoke (alias для agent_run)
    """
    builder = (
        RouteBuilder.from_("credit_check_demo", source="internal:credit_check")
        .set_description("PoC — credit check с AI Agent DSL processors (S27 W3 PoC)")
        .set_tenant_aware(True)
        .require_capability("ai.invoke")
        .require_capability("ai.memory.read")
        .require_capability("ai.memory.write")
        .require_capability("pii.tokenize.reversible")
        .require_capability("skill.invoke")
    )

    # 1. Memory recall — проверка history
    builder.ai_memory_recall(
        namespace="credit:${meta.tenant_id}",
        query="previous credit applications",
        k=3,
        result_property="body.previous_applications",
    )

    # 2. PII masking
    builder.pii_mask(
        source="body",
        target="body.masked",
        scope="banking",
        fields=["full_name", "passport", "inn", "snils"],
    )

    # 3. Guardrails input
    builder.guardrails_apply(stage="input", on_block="dlq")

    # 4. Agent parallel
    builder.agent_parallel(
        agents=[
            {
                "name": "credit_score_agent",
                "workflow_id": "credit_scoring_v1",
                "context": {
                    "income": "${body.masked.income}",
                    "employment_type": "${body.masked.employment_type}",
                },
                "timeout_s": 10,
            },
            {
                "name": "fraud_check_agent",
                "workflow_id": "fraud_detection_v1",
                "context": {"customer_id": "${body.masked.customer_id}"},
                "timeout_s": 8,
            },
            {
                "name": "compliance_agent",
                "workflow_id": "compliance_check_v1",
                "context": {"applicant": "${body.masked}"},
                "timeout_s": 12,
            },
        ],
        continue_on_error=True,
    )

    # 5. Agent branch
    builder.agent_branch(
        condition="${agent_results.credit_score_agent.verdict}",
        branches={
            "APPROVED": [{"set": {"body.decision": "approved"}}],
            "DENIED": [{"set": {"body.decision": "denied"}}],
            "REVIEW": [
                # Agent loop для уточняющих вопросов
                {
                    "agent_loop": {
                        "name": "additional_info_loop",
                        "max_iterations": 3,
                        "stop_condition": "${body.additional_info_complete}",
                        "budget": {"max_tokens": 2000, "max_cost_usd": 0.10},
                        "loop_step": {
                            "agent_run": {
                                "workflow_id": "additional_info_collection_v1",
                                "context": {"missing_fields": "${body.missing_fields}"},
                            }
                        },
                    }
                }
            ],
        },
    )

    # 6. Skill invoke
    builder.skill_invoke(
        skill_id="credit.rate_calculator",
        params={
            "amount": "${body.masked.requested_amount}",
            "term_months": "${body.masked.term_months}",
            "risk_score": "${agent_results.credit_score_agent.risk_score}",
        },
    )

    # 7. Guardrails output
    builder.guardrails_apply(stage="output", on_block="warn")

    # 8. PII unmask
    builder.pii_unmask(source="body.decision_response", target="body")

    # 9. Memory store
    builder.ai_memory_store(
        namespace="credit:${meta.tenant_id}",
        key="application:${body.application_id}",
        value="${body.decision_response}",
        ttl_s=2592000,
    )

    # Final response
    builder.to_response(
        code=200,
        body={
            "application_id": "${body.application_id}",
            "decision": "${body.decision}",
        },
    )

    route = builder.build()
    return route


if __name__ == "__main__":
    route = build_credit_check_route()
    print(f"Route built: {route.route_id}")
    print(f"Processors: {[p.name for p in route.processors]}")
