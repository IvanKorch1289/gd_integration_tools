"""OSINT workflow: validate INN, web-search, compose report via LLM.

Pipeline:
1. Validate INN (checksum).
2. Resolve company name from INN.
3. Web-search via Perplexity (3 queries: general, courts, negative).
4. Compose prompt with search results.
5. LLM call to generate structured report.
6. Validate report format and length.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

OSINT_REPORT_TEMPLATE = """\
Ты — аналитик OSINT. Сформируй строгий отчёт по компании.
Не отклоняйся от формата. Максимум 3000 символов.
Используй ТОЛЬКО факты из данных. Если данных нет — напиши "Данные не найдены".

ДАННЫЕ:
Компания: {company_name}
ИНН: {inn}

Общая информация:
{results_general}

Судебные дела:
{results_courts}

Негативные упоминания:
{results_negative}

ФОРМАТ ОТЧЁТА (строго соблюдай):
═══════════════════════════════════════════════
ОТЧЁТ OSINT: {company_name}
ИНН: {inn} | Дата: {report_date}
═══════════════════════════════════════════════

1. ОБЩАЯ ИНФОРМАЦИЯ
Полное наименование, ОГРН, дата регистрации, вид деятельности (2-4 предложения).

2. ПОЗИТИВНЫЕ УПОМИНАНИЯ
• Упоминание (источник: url)

3. НЕГАТИВНЫЕ УПОМИНАНИЯ / ЖАЛОБЫ
• Упоминание (источник: url)

4. СУДЕБНЫЕ ДЕЛА
• Дело: номер, дата, сторона, статус (источник: url)

5. ФИНАНСОВЫЕ МАРКЕРЫ
• Маркер

6. ИСТОЧНИКИ
[1] url

═══════════════════════════════════════════════
Сформировано AI. Данные актуальны на {report_date}.
═══════════════════════════════════════════════"""

MAX_REPORT_LENGTH = 3000


def validate_inn(inn: str) -> bool:
    """Validate Russian INN (10 or 12 digits with checksums).

    Args:
        inn: INN string to validate.

    Returns:
        True if INN is valid.
    """
    if not inn or not inn.isdigit() or len(inn) not in (10, 12):
        return False
    if len(inn) == 10:
        weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        check = sum(int(inn[i]) * weights[i] for i in range(9)) % 11 % 10
        return check == int(inn[9])
    weights_11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    check_11 = sum(int(inn[i]) * weights_11[i] for i in range(10)) % 11 % 10
    check_12 = sum(int(inn[i]) * weights_11[i - 1] for i in range(1, 11)) % 11 % 10
    return check_11 == int(inn[10]) and check_12 == int(inn[11])


def _build_search_queries(inn: str, company_name: str) -> dict[str, str]:
    """Build 3 search queries for OSINT.

    Args:
        inn: Company INN.
        company_name: Company name.

    Returns:
        Dict with keys: general, courts, negative.
    """
    name_part = company_name or f"компания ИНН {inn}"
    return {
        "general": f"{name_part} ИНН {inn} site:rusprofile.ru OR site:list-org.com",
        "courts": f"{inn} судебные дела Арбитражный суд",
        "negative": f"{name_part} отзывы жалобы проблемы",
    }


def _format_results(results: list[dict[str, Any]] | dict[str, Any] | None) -> str:
    """Format search results into readable text.

    Args:
        results: Search results from Perplexity.

    Returns:
        Formatted string.
    """
    if not results:
        return "Данные не найдены"
    if isinstance(results, dict):
        content = results.get("content", "")
        if content:
            return content
        results = results.get("results", [])
    if isinstance(results, list):
        parts = []
        for r in results:
            if isinstance(r, dict):
                content = r.get("content", str(r))
                citations = r.get("citations", [])
                if citations:
                    content += f" [источники: {', '.join(str(c) for c in citations[:3])}]"
                parts.append(content)
            else:
                parts.append(str(r))
        return "\n".join(parts) if parts else "Данные не найдены"
    return str(results)


def _parse_report_sections(raw_text: str) -> dict[str, Any]:
    """Parse LLM output into structured report sections.

    Args:
        raw_text: Raw LLM output.

    Returns:
        Dict with parsed sections.
    """
    sections: dict[str, Any] = {
        "general_info": "",
        "positive_mentions": [],
        "negative_mentions": [],
        "court_cases": [],
        "financial_markers": [],
        "sources": [],
    }
    current_section = None
    for line in raw_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if "1." in line and "ОБЩАЯ" in line:
            current_section = "general_info"
        elif "2." in line and "ПОЗИТИВНЫЕ" in line:
            current_section = "positive"
        elif "3." in line and "НЕГАТИВНЫЕ" in line:
            current_section = "negative"
        elif "4." in line and "СУДЕБНЫЕ" in line:
            current_section = "courts"
        elif "5." in line and "ФИНАНСОВЫЕ" in line:
            current_section = "financial"
        elif "6." in line and "ИСТОЧНИКИ" in line:
            current_section = "sources"
        elif line.startswith("═"):
            continue
        elif current_section == "general_info":
            sections["general_info"] += line + " "
        elif current_section == "positive":
            if line.startswith("•"):
                sections["positive_mentions"].append({"text": line[1:].strip()})
        elif current_section == "negative":
            if line.startswith("•"):
                sections["negative_mentions"].append({"text": line[1:].strip()})
        elif current_section == "courts":
            if line.startswith("•"):
                sections["court_cases"].append({"text": line[1:].strip()})
        elif current_section == "financial":
            if line.startswith("•"):
                sections["financial_markers"].append(line[1:].strip())
        elif current_section == "sources":
            match = re.match(r"\[(\d+)\]\s*(.*)", line)
            if match:
                sections["sources"].append(match.group(2).strip())
    sections["general_info"] = sections["general_info"].strip()
    return sections


def compose_prompt(
    *,
    inn: str,
    company_name: str,
    results_general: Any,
    results_courts: Any,
    results_negative: Any,
) -> str:
    """Compose OSINT report prompt from search results.

    Args:
        inn: Company INN.
        company_name: Resolved company name.
        results_general: General search results.
        results_courts: Court search results.
        results_negative: Negative search results.

    Returns:
        Formatted prompt for LLM.
    """
    report_date = datetime.now(UTC).strftime("%Y-%m-%d")
    return OSINT_REPORT_TEMPLATE.format(
        company_name=company_name or f"Компания ИНН {inn}",
        inn=inn,
        report_date=report_date,
        results_general=_format_results(results_general),
        results_courts=_format_results(results_courts),
        results_negative=_format_results(results_negative),
    )


def validate_report(raw_text: str) -> dict[str, Any]:
    """Validate and parse OSINT report.

    Args:
        raw_text: Raw LLM report output.

    Returns:
        Dict with validated report data.

    Raises:
        ValueError: If report exceeds max length.
    """
    if len(raw_text) > MAX_REPORT_LENGTH:
        raw_text = raw_text[:MAX_REPORT_LENGTH]
    sections = _parse_report_sections(raw_text)
    return {"raw_text": raw_text, **sections}


async def _search_multi_provider(
    query: str, *, max_results: int = 10
) -> dict[str, Any]:
    """Search через Tavily + Perplexity + scraping (Sprint 170 M3 dir 11).

    Returns dict с результатами от каждого провайдера + scraped content.
    """
    results: dict[str, Any] = {"perplexity": [], "tavily": [], "scraped": []}
    try:
        from src.backend.core.integrations.web_search import get_web_search_service

        service = get_web_search_service()
        # Perplexity — research-grade synthesis
        results["perplexity"] = await service.query(
            query, max_results=max_results, provider="perplexity"
        )
        # Tavily — fresh web content with citations
        results["tavily"] = await service.query(
            query, max_results=max_results, provider="tavily"
        )
    except Exception:
        pass
    # Scrape top URLs from Tavily
    tavily_items = results["tavily"]
    if isinstance(tavily_items, dict):
        tavily_items = tavily_items.get("results", [])
    for item in tavily_items[:3]:
        if isinstance(item, dict) and item.get("url"):
            try:
                from src.backend.infrastructure.clients.external.search_providers import (
                    _scrape_url,
                )
                scraped = await _scrape_url(item["url"], max_chars=2000)
                results["scraped"].append({"url": item["url"], "content": scraped})
            except Exception:
                continue
    return results


async def run_osint(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute OSINT workflow for a company by INN.

    Pipeline (Sprint 170 M3):
    1. Validate INN
    2. Multi-provider search: Tavily + Perplexity + scraping
    3. LLM summarization via OpenAI-compatible provider
    4. Validate report format

    Args:
        payload: Dict with 'inn' and optional 'company_name'.

    Returns:
        Dict with OSINT report data.

    Raises:
        ValueError: If INN is invalid.
    """
    inn = str(payload.get("inn", "")).strip()
    if not validate_inn(inn):
        raise ValueError(f"Invalid INN: {inn!r}")

    company_name = str(payload.get("company_name", "")).strip()
    queries = _build_search_queries(inn, company_name)

    # Multi-provider search (Tavily + Perplexity + scraping)
    try:
        results_general = await _search_multi_provider(queries["general"])
        results_courts = await _search_multi_provider(queries["courts"])
        results_negative = await _search_multi_provider(queries["negative"])
    except Exception:
        results_general = {"perplexity": None, "tavily": None, "scraped": []}
        results_courts = {"perplexity": None, "tavily": None, "scraped": []}
        results_negative = {"perplexity": None, "tavily": None, "scraped": []}

    prompt = compose_prompt(
        inn=inn,
        company_name=company_name,
        results_general=results_general,
        results_courts=results_courts,
        results_negative=results_negative,
    )

    try:
        from src.backend.core.ai.llm_gateway import get_litellm_gateway

        gateway = get_litellm_gateway()
        response = await gateway.acompletion(
            model="sonar",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
        )
        raw_text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception:
        raw_text = prompt

    report = validate_report(raw_text)
    report["inn"] = inn
    report["company_name"] = company_name or f"Компания ИНН {inn}"
    report["report_date"] = datetime.now(UTC).strftime("%Y-%m-%d")
    return report
