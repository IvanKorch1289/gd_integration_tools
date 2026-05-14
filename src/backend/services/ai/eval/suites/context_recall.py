"""context_recall suite — recall@k для RAG retrieval (K4 S6 W1).

Каждый sample = (question, ground_truth_doc_ids, retrieved_doc_ids@k).
Метрики: recall@k, precision@k, mrr@k.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class _ContextRecall:
    name: str = "context_recall"
    description: str = "RAG retrieval recall@k / precision@k / MRR"

    def build_dataset(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "rec-1",
                "question": "Условия кредитной карты Platinum",
                "ground_truth": ["doc-cc-platinum-1", "doc-cc-platinum-2"],
                "expected": "doc-cc-platinum-1 doc-cc-platinum-2 doc-cc-gold-1",
            },
            {
                "id": "rec-2",
                "question": "Тарифы РКО для ИП",
                "ground_truth": ["doc-rko-ip-1"],
                "expected": "doc-rko-ip-1 doc-rko-juridical-1",
            },
            {
                "id": "rec-3",
                "question": "Ипотека на новостройку",
                "ground_truth": ["doc-mortg-new-1", "doc-mortg-new-2", "doc-mortg-policy-1"],
                "expected": "doc-mortg-policy-1 doc-mortg-new-1 doc-mortg-new-2",
            },
            {
                "id": "rec-4",
                "question": "Документы для онбординга ИП",
                "ground_truth": ["doc-onboard-ip-1"],
                "expected": "doc-onboard-ip-1",
            },
            {
                "id": "rec-5",
                "question": "Лимиты по СБП",
                "ground_truth": ["doc-sbp-limits-1"],
                "expected": "doc-sbp-limits-1 doc-pay-fee-1",
            },
        ]

    def score(self, sample: dict[str, Any], output: str) -> dict[str, float]:
        retrieved = [item.strip() for item in (output or "").split() if item.strip()]
        ground_truth = set(sample.get("ground_truth") or [])

        if not ground_truth or not retrieved:
            return {"recall_at_k": 0.0, "precision_at_k": 0.0, "mrr": 0.0}

        retrieved_set = set(retrieved)
        hit = ground_truth & retrieved_set
        recall = len(hit) / len(ground_truth)
        precision = len(hit) / len(retrieved)
        mrr = 0.0
        for rank, doc in enumerate(retrieved, start=1):
            if doc in ground_truth:
                mrr = 1.0 / rank
                break
        return {
            "recall_at_k": float(recall),
            "precision_at_k": float(precision),
            "mrr": float(mrr),
        }


context_recall_suite = _ContextRecall()
__all__ = ("context_recall_suite",)
