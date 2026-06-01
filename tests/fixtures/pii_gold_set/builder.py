"""Генератор gold-set 500 ru-банковских docs для PIITokenizer round-trip.

Sprint 25 W4 / ADR-NEW-21 / ADR-0068.

Строит 500 уникальных предложений на основе templates × PII-комбинаций.
Каждый doc гарантированно содержит хотя бы по одной PII-сущности из набора
``(PERSON, INN, SNILS, PHONE_NUMBER, CONTRACT)`` — все типы покрыты
:class:`MockPresidioAdapter` (см. ``test_pii_tokenizer_roundtrip.py``).

Использование::

    from tests.fixtures.pii_gold_set.builder import build_reversible_gold_set
    docs = build_reversible_gold_set()
    assert len(docs) == 500
    for doc in docs:
        assert doc["expected_entities"]  # все PII покрыты

YAML-сериализация для review/docs:

    python -m tests.fixtures.pii_gold_set.builder > tests/fixtures/pii_gold_set/reversible.yaml
"""

from __future__ import annotations

import sys
from typing import TypedDict


class GoldSetDoc(TypedDict):
    id: str
    text: str
    expected_entities: list[str]


# ── Templates (10) ─────────────────────────────────────────────────────────

_TEMPLATES: tuple[str, ...] = (
    "Клиент {name} (ИНН {inn}, СНИЛС {snils}) обратился по договору № {contract} с тел. {phone}.",
    "Уважаемый {name}, по вашему обращению № {contract} принято решение. Контактный телефон: {phone}.",
    "Подтверждаем, что {name}, ИНН {inn}, провёл операцию по договору № {contract}.",
    "Клиент {name} запросил выписку по договору № {contract}. ИНН: {inn}, СНИЛС: {snils}.",
    "По вопросам обращайтесь: {name}, тел. {phone}, договор № {contract}.",
    "Договор № {contract} заключён с {name} (ИНН {inn}). Контакт: {phone}.",
    "Гражданин {name}, СНИЛС {snils}, погасил задолженность по договору № {contract}.",
    "{name} обратился в банк по вопросу договора № {contract}. ИНН клиента: {inn}, тел.: {phone}.",
    "Просим связаться с клиентом {name} по тел. {phone} по вопросу договора № {contract}.",
    "Заявка от {name} (ИНН {inn}, тел. {phone}) по договору № {contract} принята в работу.",
)

# ── PII variants ───────────────────────────────────────────────────────────

_NAMES: tuple[str, ...] = (
    "Иванов И.И.",
    "Петров А.С.",
    "Сидоров В.К.",
    "Кузнецов Д.М.",
    "Соколов Е.А.",
    "Морозов П.Н.",
    "Васильев С.Б.",
    "Зайцев Р.В.",
    "Павлов Н.О.",
    "Семёнов К.Л.",
)

_INNS: tuple[str, ...] = (
    "7707083893",
    "5260270518",
    "7704211201",
    "6671266100",
    "7716098460",
)

_SNILS: tuple[str, ...] = (
    "112-233-445 95",
    "987-654-321 00",
    "555-666-777 12",
    "111-222-333 44",
    "999-888-777 66",
)

_PHONES: tuple[str, ...] = (
    "+7-999-123-45-67",
    "+7-495-987-65-43",
    "+7-812-555-44-33",
    "+7-916-777-88-99",
    "+7-903-222-11-00",
)

_CONTRACTS: tuple[str, ...] = (
    "12345/CR-001",
    "67890/DV-002",
    "11111/CR-003",
    "22222/IP-004",
    "33333/DV-005",
)


def build_reversible_gold_set(n: int = 500) -> list[GoldSetDoc]:
    """Возвращает list из ``n`` GoldSetDoc (по умолчанию 500).

    Каждый doc — уникальная комбинация ``(template, name, inn, snils, phone, contract)``.
    Полный декартов продукт = 10 × 10 × 5 × 5 × 5 × 5 = 62500 — достаточно.
    """
    docs: list[GoldSetDoc] = []
    counter = 0
    for template in _TEMPLATES:
        for name in _NAMES:
            for inn in _INNS:
                for snils in _SNILS:
                    for phone in _PHONES:
                        for contract in _CONTRACTS:
                            if counter >= n:
                                return docs
                            text = template.format(
                                name=name,
                                inn=inn,
                                snils=snils,
                                phone=phone,
                                contract=contract,
                            )
                            entities = _expected_entities_in(template)
                            docs.append(
                                {
                                    "id": f"doc-{counter:04d}",
                                    "text": text,
                                    "expected_entities": entities,
                                }
                            )
                            counter += 1
    return docs


def _expected_entities_in(template: str) -> list[str]:
    """Возвращает список PII-типов, которые есть в данном template."""
    mapping = {
        "{name}": "PERSON",
        "{inn}": "INN",
        "{snils}": "SNILS",
        "{phone}": "PHONE_NUMBER",
        "{contract}": "CONTRACT",
    }
    return sorted({entity for marker, entity in mapping.items() if marker in template})


def _dump_yaml(docs: list[GoldSetDoc]) -> str:
    """Сериализует docs в простой YAML (без зависимости от PyYAML)."""
    lines = ["# PII gold-set — Sprint 25 W4 (ADR-0068)\n"]
    lines.append(f"# Total: {len(docs)} docs\n")
    lines.append("docs:\n")
    for doc in docs:
        lines.append(f"  - id: {doc['id']}\n")
        text_escaped = doc["text"].replace('"', '\\"')
        lines.append(f'    text: "{text_escaped}"\n')
        lines.append(
            f"    expected_entities: [{', '.join(doc['expected_entities'])}]\n"
        )
    return "".join(lines)


if __name__ == "__main__":
    docs = build_reversible_gold_set()
    sys.stdout.write(_dump_yaml(docs))
