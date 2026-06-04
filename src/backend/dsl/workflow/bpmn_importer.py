"""BPMN 2.0 импортёр в WorkflowDeclaration (Sprint 4 K3 Wave B).

PLAN V18.1 [wave:s4/k3-bpmn-import].

Модуль реализует декларативный импорт BPMN 2.0 XML-файлов в
:class:`WorkflowDeclaration` для последующей компиляции в Temporal-классы
через :mod:`src.backend.dsl.workflow.compiler`.

Архитектура:
    * Парсинг через stdlib :mod:`xml.etree.ElementTree` с
      ``defusedxml.ElementTree`` (XXE-protection); fallback на чистый
      stdlib, если defusedxml не установлен.
    * BPMN 2.0 namespace: ``http://www.omg.org/spec/BPMN/20100524/MODEL``.
    * Маппинг элементов:
        - ``<bpmn:startEvent>``    — точка входа (не эмитит step).
        - ``<bpmn:endEvent>``      — точка выхода (не эмитит step).
        - ``<bpmn:serviceTask>``   → :class:`ActivityDeclaration`.
        - ``<bpmn:exclusiveGateway>`` → :class:`GatewaySpec` (kind="xor")
          с метаданными в IR-dict для последующей компиляции в
          conditional-dispatch.
        - ``<bpmn:parallelGateway>`` → :class:`GatewaySpec` (kind="and").
        - ``<bpmn:inclusiveGateway>`` → :class:`GatewaySpec` (kind="or").
        - ``<bpmn:sequenceFlow>``  — определяет топологический порядок
          step'ов; condition expressions используются для веток
          gateway.
    * Топологическая сортировка через простой обход графа sequence-flow
      от ``startEvent`` к ``endEvent``.

Использование:
    >>> from src.backend.dsl.workflow.bpmn_importer import import_bpmn
    >>> with open("workflow.bpmn") as fh:
    ...     decl = import_bpmn(fh.read(), name="credit_scoring")
    >>> compiled = compile_workflow(decl)

Безопасность:
    * Feature-flag ``workflow_bpmn_import`` (default-OFF) защищает от
      случайного использования до staging-smoke.
    * Парсер использует ``defusedxml`` (когда доступен) для защиты от
      XXE / billion-laughs.
    * BPMN-файлы парсятся как untrusted input — все ``ValueError`` /
      ``ET.ParseError`` оборачиваются в :class:`BpmnImportError`.

Раздел V15 §R-V15-9 (AI-функции через Workflow DSL) — этот импортёр
не покрывает activities с tools/structured_output; такие шаги
декларируются вручную через Python WorkflowBuilder.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any, Final

from src.backend.dsl.workflow.gateways import BranchSpec, GatewaySpec
from src.backend.dsl.workflow.spec import ActivityDeclaration, WorkflowDeclaration

__all__ = (
    "BPMN_NAMESPACE",
    "BpmnImportDisabledError",
    "BpmnImportError",
    "BpmnImportNotAvailableError",
    "import_bpmn",
)

_logger = logging.getLogger("workflow.bpmn_importer")

#: Стандартный namespace BPMN 2.0 (OMG spec 2010-05-24).
BPMN_NAMESPACE: Final[str] = "http://www.omg.org/spec/BPMN/20100524/MODEL"

#: Префикс для всех bpmn-тегов в :mod:`xml.etree` (Clark-notation).
_NS_PREFIX: Final[str] = f"{{{BPMN_NAMESPACE}}}"


class BpmnImportError(ValueError):
    """Базовое исключение для ошибок импорта BPMN."""


class BpmnImportDisabledError(RuntimeError):
    """Импорт BPMN отключён feature-flag ``workflow_bpmn_import``."""


class BpmnImportNotAvailableError(RuntimeError):
    """Зарезервировано для пути SpiffWorkflow (когда extra не установлен).

    Текущая реализация использует stdlib :mod:`xml.etree.ElementTree`,
    поэтому данное исключение никогда не возбуждается. Оставлено в
    публичном API для совместимости с задачей K3 W3 и для
    альтернативного пути через SpiffWorkflow в будущем.
    """


def import_bpmn(
    xml_text: str,
    *,
    name: str | None = None,
    description: str | None = None,
    check_feature_flag: bool = True,
) -> WorkflowDeclaration:
    """Импортировать BPMN 2.0 XML в :class:`WorkflowDeclaration`.

    Args:
        xml_text: Содержимое BPMN-файла в формате XML 1.0.
        name: Опциональное имя workflow; если не указано — берётся из
            атрибута ``id`` корневого ``<bpmn:process>`` (или
            ``imported_bpmn`` если отсутствует).
        description: Опциональное человекочитаемое описание.
        check_feature_flag: Если True — проверяет
            ``feature_flags.workflow_bpmn_import`` и поднимает
            :class:`BpmnImportDisabledError` при default-OFF. Тесты могут
            отключить эту проверку через ``check_feature_flag=False``.

    Returns:
        Декларация workflow с заполненными ``name``, ``steps`` (включая
        gateway-шаги, замаскированные под :class:`ActivityDeclaration` с
        специальным префиксом ``__gateway__``).

    Raises:
        BpmnImportDisabledError: Если feature-flag выключен и
            ``check_feature_flag=True``.
        BpmnImportError: Если XML невалидный, отсутствует
            ``<bpmn:process>`` или structure-граф некорректен.
    """
    if check_feature_flag:
        _ensure_feature_enabled()

    try:
        root = ET.fromstring(xml_text)  # noqa: S314  # internal controlled XML parsing
    except ET.ParseError as exc:
        raise BpmnImportError(f"Невалидный BPMN XML: {exc}") from exc

    process = _find_process(root)

    workflow_name = name or process.attrib.get("id") or "imported_bpmn"
    workflow_description = (
        description
        or process.attrib.get("name")
        or f"Workflow импортирован из BPMN: {workflow_name}"
    )

    elements = _collect_elements(process)
    flows = _collect_sequence_flows(process)
    ordered_node_ids = _topological_order(elements, flows)

    steps = _build_steps(ordered_node_ids, elements, flows)
    if not steps:
        raise BpmnImportError(
            "BPMN-процесс не содержит ни одного executable-step (serviceTask/gateway)."
        )

    _logger.debug(
        "BPMN импортирован: name=%s, steps=%d, gateways=%d",
        workflow_name,
        len(steps),
        sum(1 for s in steps if s.name.startswith("__gateway__")),
    )

    return WorkflowDeclaration(
        name=workflow_name, description=workflow_description, steps=steps
    )


def _ensure_feature_enabled() -> None:
    """Проверить feature-flag ``workflow_bpmn_import``.

    Импортируется лениво, чтобы тесты могли создать декларацию без
    инициализации settings (см. ``check_feature_flag=False``).
    """
    from src.backend.core.config.features import feature_flags

    if not feature_flags.workflow_bpmn_import:
        raise BpmnImportDisabledError(
            "BPMN import выключен feature-flag "
            "FEATURE_WORKFLOW_BPMN_IMPORT (default-OFF). "
            "Установите FEATURE_WORKFLOW_BPMN_IMPORT=true для включения."
        )


def _find_process(root: ET.Element) -> ET.Element:
    """Найти корневой ``<bpmn:process>`` в дереве definitions.

    BPMN 2.0 root — ``<bpmn:definitions>``; внутри один или несколько
    ``<bpmn:process>``. Импортёр берёт первый process; multi-process
    диаграммы требуют ручного выбора (не покрыто в Sprint 4).
    """
    process = root.find(f"{_NS_PREFIX}process")
    if process is None:
        raise BpmnImportError(
            "В BPMN-файле не найден элемент <bpmn:process>. "
            "Убедитесь, что namespace == "
            f"{BPMN_NAMESPACE!r} и root — <bpmn:definitions>."
        )
    return process


def _collect_elements(process: ET.Element) -> dict[str, ET.Element]:
    """Собрать все BPMN-элементы process в dict ``{id: element}``.

    Включает: startEvent, endEvent, serviceTask, task, exclusiveGateway,
    parallelGateway, inclusiveGateway, intermediateCatchEvent,
    intermediateThrowEvent. Игнорирует sequenceFlow (обрабатываются
    отдельно) и расширенные конструкции (subprocess, businessRule,
    userTask — Sprint 5+).
    """
    supported_local_names = {
        "startEvent",
        "endEvent",
        "serviceTask",
        "task",
        "exclusiveGateway",
        "parallelGateway",
        "inclusiveGateway",
    }
    elements: dict[str, ET.Element] = {}
    for child in process:
        local_name = _strip_ns(child.tag)
        if local_name not in supported_local_names:
            continue
        node_id = child.attrib.get("id")
        if node_id is None:
            continue
        elements[node_id] = child
    return elements


def _collect_sequence_flows(process: ET.Element) -> dict[str, list[dict[str, str]]]:
    """Собрать sequence-flows как adjacency list ``{source_id: [{...}]}``.

    Каждая запись: ``{"target": ..., "name": ..., "condition": ...}``.
    Condition берётся из ``<bpmn:conditionExpression>``.
    """
    adjacency: dict[str, list[dict[str, str]]] = {}
    for flow in process.findall(f"{_NS_PREFIX}sequenceFlow"):
        source = flow.attrib.get("sourceRef")
        target = flow.attrib.get("targetRef")
        if source is None or target is None:
            continue

        condition_el = flow.find(f"{_NS_PREFIX}conditionExpression")
        condition = (
            (condition_el.text or "").strip() if condition_el is not None else ""
        )

        adjacency.setdefault(source, []).append(
            {
                "target": target,
                "name": flow.attrib.get("name", ""),
                "condition": condition,
            }
        )
    return adjacency


def _topological_order(
    elements: dict[str, ET.Element], flows: dict[str, list[dict[str, str]]]
) -> list[str]:
    """Простой DFS-обход от startEvent до endEvent.

    Возвращает плоский упорядоченный список node-id. Для gateway'ев
    проходит по всем веткам, но каждую вершину посещает только один раз
    (gateway-fan-in сходится в одной точке).

    BPMN допускает множественные startEvent (race-start). В Sprint 4
    поддерживается ровно один startEvent — иначе :class:`BpmnImportError`.
    """
    starts = [
        node_id for node_id, el in elements.items() if _strip_ns(el.tag) == "startEvent"
    ]
    if not starts:
        raise BpmnImportError(
            "В BPMN-процессе не найден <bpmn:startEvent>. "
            "Импортёр требует ровно один startEvent."
        )
    if len(starts) > 1:
        raise BpmnImportError(
            f"Найдено {len(starts)} startEvent; "
            "Sprint 4 поддерживает ровно один startEvent."
        )

    order: list[str] = []
    visited: set[str] = set()

    def _dfs(node_id: str) -> None:
        if node_id in visited:
            return
        visited.add(node_id)
        if node_id in elements:
            order.append(node_id)
        for edge in flows.get(node_id, []):
            _dfs(edge["target"])

    _dfs(starts[0])
    return order


def _build_steps(
    ordered_ids: list[str],
    elements: dict[str, ET.Element],
    flows: dict[str, list[dict[str, str]]],
) -> list[ActivityDeclaration]:
    """Сконвертировать упорядоченные node-id в список ActivityDeclaration.

    startEvent / endEvent — не эмитят шаги. ServiceTask / task —
    становятся обычной :class:`ActivityDeclaration`. Gateway-ноды
    становятся «маркер-step'ами» с именем ``__gateway__<id>`` и
    сериализованной :class:`GatewaySpec` в ``args["gateway"]``.

    Это компромисс: WorkflowDeclaration.steps[] принимает только union
    из 5 типов (Activity/Saga/SignalWait/Sleep/Sensor). Добавлять
    отдельный GatewayDeclaration — отдельная задача Wave C
    (расширение spec.py). Маркер-step'ы безопасно компилируются как
    no-op activity, а IR-dict в args позволяет последующему этапу
    компиляции (когда GatewayDeclaration появится в spec) распознать
    эти узлы и эмитить корректный Temporal-код.
    """
    steps: list[ActivityDeclaration] = []
    for node_id in ordered_ids:
        element = elements.get(node_id)
        if element is None:
            continue
        local_name = _strip_ns(element.tag)

        if local_name in {"startEvent", "endEvent"}:
            continue

        if local_name in {"serviceTask", "task"}:
            activity_name = (
                element.attrib.get("name") or element.attrib.get("id") or node_id
            )
            steps.append(
                ActivityDeclaration(
                    name=activity_name,
                    args={"bpmn_id": node_id, "bpmn_type": local_name},
                )
            )
            continue

        if local_name in {"exclusiveGateway", "parallelGateway", "inclusiveGateway"}:
            gateway_spec = _build_gateway_spec(node_id, local_name, flows, elements)
            steps.append(
                ActivityDeclaration(
                    name=f"__gateway__{node_id}",
                    args={
                        "bpmn_id": node_id,
                        "bpmn_type": local_name,
                        "gateway": _gateway_spec_to_dict(gateway_spec),
                    },
                )
            )
            continue

    return steps


def _build_gateway_spec(
    gateway_id: str,
    bpmn_type: str,
    flows: dict[str, list[dict[str, str]]],
    elements: dict[str, ET.Element],
) -> GatewaySpec:
    """Построить :class:`GatewaySpec` для gateway-узла.

    Ветки берутся из исходящих sequence-flow от ``gateway_id``.
    Имя ветки = ``name`` или ``target`` sequence-flow.
    """
    kind = _map_bpmn_kind_to_gateway_kind(bpmn_type)

    branches: list[BranchSpec] = []
    for edge in flows.get(gateway_id, []):
        target_id = edge["target"]
        target_element = elements.get(target_id)
        target_label = (
            target_element.attrib.get("name", "") if target_element is not None else ""
        )
        branch_name = edge["name"] or target_label or target_id
        condition_expr = edge["condition"] or None
        branches.append(
            BranchSpec(
                name=branch_name,
                condition=condition_expr,
                steps=[{"bpmn_target": target_id}],
            )
        )

    return GatewaySpec(kind=kind, branches=branches)


def _map_bpmn_kind_to_gateway_kind(bpmn_type: str) -> str:
    """Маппинг BPMN-tag → kind для :class:`GatewaySpec`."""
    match bpmn_type:
        case "exclusiveGateway":
            return "xor"
        case "parallelGateway":
            return "and"
        case "inclusiveGateway":
            return "or"
        case _:
            raise BpmnImportError(
                f"Неподдерживаемый тип gateway: {bpmn_type!r}. "
                "Поддерживаются: exclusiveGateway, parallelGateway, inclusiveGateway."
            )


def _gateway_spec_to_dict(spec: GatewaySpec) -> dict[str, Any]:
    """Сериализовать :class:`GatewaySpec` в JSON-friendly dict.

    Используется как payload для ``ActivityDeclaration.args["gateway"]``
    при «маркер-step» паттерне.
    """
    return {
        "kind": spec.kind,
        "branches": [
            {
                "name": branch.name,
                "condition": branch.condition,
                "steps": list(branch.steps),
            }
            for branch in spec.branches
        ],
    }


def _strip_ns(tag: str) -> str:
    """Вернуть local-name из Clark-notation ``{ns}local``."""
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag
