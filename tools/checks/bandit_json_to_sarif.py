"""Конвертер bandit JSON -> SARIF 2.1.0 для GitHub code scanning.

Контекст
--------
Аудит 2026-09-21: bandit 1.9.x не имеет встроенного формата ``sarif``
(``-f sarif`` -> ``invalid choice``), из-за чего шаг bandit в
security.yml падал на argparse ещё ДО блокирующего HIGH-гейта.
Конвертер строит SARIF из штатного JSON-вывода bandit без новых
зависимостей (только stdlib).

Использование
-------------
::

    uv run bandit -r src -c .bandit -f json -o bandit.json
    uv run python tools/checks/bandit_json_to_sarif.py bandit.json bandit.sarif
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_LEVEL = {"HIGH": "error", "MEDIUM": "warning", "LOW": "note"}


def convert(bandit_json: dict) -> dict:
    """Построить SARIF-документ из распарсенного JSON-отчёта bandit."""
    results = bandit_json.get("results", [])
    rule_ids = sorted({str(r.get("test_id", "")) for r in results})
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "bandit",
                        "informationUri": "https://bandit.readthedocs.io/",
                        "rules": [{"id": rid} for rid in rule_ids],
                    }
                },
                "results": [
                    {
                        "ruleId": str(r.get("test_id", "")),
                        "level": _LEVEL.get(
                            str(r.get("issue_severity", "LOW")).upper(), "note"
                        ),
                        "message": {
                            "text": (
                                f"{r.get('issue_text', '')} "
                                f"[{r.get('test_id', '')} / "
                                f"{r.get('issue_confidence', '')} confidence]"
                            ).strip()
                        },
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {
                                        "uri": str(
                                            r.get("filename", "")
                                        ).lstrip("./"),
                                    },
                                    "region": {
                                        "startLine": int(
                                            r.get("line_number") or 1
                                        ),
                                    },
                                }
                            }
                        ],
                    }
                    for r in results
                ],
            }
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: два позиционных аргумента — вход bandit JSON, выход SARIF."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(
            "usage: bandit_json_to_sarif.py <bandit.json> <bandit.sarif>",
            file=sys.stderr,
        )
        return 2
    src, dst = Path(args[0]), Path(args[1])
    report = json.loads(src.read_text(encoding="utf-8"))
    dst.write_text(
        json.dumps(convert(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    n = len(report.get("results", []))
    print(f"SARIF записан: {dst} ({n} results)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
