#!/usr/bin/env python3
"""
render_permissions.py — единый source of truth → Claude JSON + Kimi TOML.

Source:  .shared/permissions.yaml
Output:  .claude/settings.json   (только секция `permissions` перезаписывается)
         .kimi-code/config.toml  (только `[[permission]]` блоки перезаписываются)

Использование:
    python .shared/sync/render_permissions.py          # regenerate
    python .shared/sync/render_permissions.py --verify # drift check (exit 1 при дрейфе)

ВАЖНО: Claude и Kimi используют РАЗНЫЕ pattern-синтаксисы:
  Claude: Tool(cmd:arg) — colon отделяет cmd от args
  Kimi:   Tool(cmd arg *) — shell-glob

Поэтому каждое правило в YAML имеет:
  - `pattern:` — Claude-форма (основная)
  - `kimi:`    — Kimi-форма (если отличается)

Генератор НЕ конвертирует patterns — использует raw-значения из YAML.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
YAML_FILE = PROJECT / ".shared" / "permissions.yaml"
CLAUDE_FILE = PROJECT / ".claude" / "settings.json"
KIMI_FILE = PROJECT / ".kimi-code" / "config.toml"

GENERATED_HEADER = (
    "# Секция permission-rules AUTO-GENERATED from .shared/permissions.yaml — do not edit.\n"
    "# Regenerate: make sync-permissions\n"
)


# === Mini YAML parser ===

def parse_simple_yaml(text: str) -> dict:
    result = {"allow": [], "ask": [], "deny": [], "vault": {}}
    section = None
    sub = None
    current_entry = None
    for raw in text.split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        # Comments — обрабатываем agent-метки
        if stripped.startswith("#"):
            if current_entry is not None and "# agent:" in stripped:
                m = re.search(r"#\s*agent:\s*([\w,\- ]+)", stripped)
                if m:
                    tag = m.group(1).strip()
                    if "claude-only" in tag:
                        current_entry["agent"] = "claude"
                    elif "kimi-only" in tag:
                        current_entry["agent"] = "kimi"
            continue
        if stripped in ("allow:", "ask:", "deny:"):
            if section == "vault":
                sub = stripped[:-1]
                result["vault"].setdefault(sub, [])
            else:
                section = stripped[:-1]
                sub = None
            continue
        if stripped == "vault:":
            section = "vault"
            sub = None
            continue
        if section == "vault" and sub and stripped.startswith("- "):
            val = stripped[2:].strip()
            if "  #" in val:
                val = val.split("  #", 1)[0].rstrip()
            result["vault"][sub].append(val)
            continue
        if section in ("allow", "ask", "deny") and stripped.startswith("- pattern:"):
            m = re.match(r"-\s+pattern:\s+['\"]?(.*?)['\"]?\s*$", stripped)
            if not m:
                continue
            pat = m.group(1)
            current_entry = {"pattern": pat if pat != "null" else None, "kimi": None, "reason": "", "agent": "both"}
            result[section].append(current_entry)
            continue
        if current_entry is not None and stripped.startswith("kimi:"):
            m = re.match(r"kimi:\s+['\"]?(.*?)['\"]?\s*$", stripped)
            if m:
                current_entry["kimi"] = m.group(1)
            continue
        if current_entry is not None and stripped.startswith("reason:"):
            m = re.match(r"reason:\s+['\"]?(.*?)['\"]?\s*$", stripped)
            if m:
                current_entry["reason"] = m.group(1)
            continue
    return result


# === Renderers ===

def render_claude(parsed: dict) -> dict:
    perm = {"allow": [], "ask": [], "deny": []}
    for section in ("allow", "ask", "deny"):
        for entry in parsed[section]:
            if entry["agent"] == "kimi":
                continue
            if entry["pattern"]:
                perm[section].append(entry["pattern"])
    # Vault → Read permissions
    for entry in parsed.get("vault", {}).get("allow", []):
        # entry may be '"./vault/SESSIONS.md"' (with YAML quotes) — strip them
        val = entry.strip().strip("'").strip('"')
        if val.startswith("./"):
            val = val[2:]
        perm["allow"].append(f"Read({val})")
    return perm


def render_kimi(parsed: dict) -> str:
    blocks = []
    for section in ("allow", "ask", "deny"):
        for entry in parsed[section]:
            if entry["agent"] == "claude":
                continue
            pat = entry["kimi"] or entry["pattern"]
            if not pat:
                continue
            reason = entry.get("reason", "") or "auto-generated"
            blocks.append(
                f'[[permission]]\ndecision = "{section}"\npattern = "{pat}"\nreason = "{reason}"\n'
            )
    # Vault → Read permissions
    for entry in parsed.get("vault", {}).get("allow", []):
        val = entry.strip().strip("'").strip('"')
        if val.startswith("./"):
            val = val[2:]
        blocks.append(
            f'[[permission]]\ndecision = "allow"\npattern = "Read({val})"\nreason = "vault rule (auto-generated)"\n'
        )
    return "\n".join(blocks) + "\n" if blocks else ""


# === File surgery ===

def update_claude_file(perm: dict) -> None:
    text = CLAUDE_FILE.read_text()
    obj = json.loads(text)
    obj["permissions"] = perm
    obj["_generated"] = "from .shared/permissions.yaml (do not edit — run make sync-permissions)"
    CLAUDE_FILE.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def update_kimi_file(blocks: str) -> None:
    text = KIMI_FILE.read_text()
    new_text = re.sub(
        r"\[\[permission\]\][^\[]*?(?=\n\[\[|\n# === |\Z)",
        "",
        text,
        flags=re.DOTALL,
    )
    new_text = new_text.rstrip() + "\n\n" + GENERATED_HEADER + "\n" + blocks
    KIMI_FILE.write_text(new_text)


# === Verify ===

def extract_kimi_blocks(text: str) -> list[str]:
    """Возвращает список [[permission]] блоков (нормализованных для сравнения)."""
    blocks = re.findall(r"\[\[permission\]\][^\[]*?(?=\n\[\[|\n# === |\Z)", text, re.DOTALL)
    return sorted(b.strip() for b in blocks)


# === Main ===

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="drift check (exit 1 при дрейфе)")
    args = parser.parse_args()

    parsed = parse_simple_yaml(YAML_FILE.read_text())
    perm_claude = render_claude(parsed)
    kimi_blocks = render_kimi(parsed)

    if args.verify:
        actual_claude = json.loads(CLAUDE_FILE.read_text()).get("permissions", {})
        actual_kimi = KIMI_FILE.read_text()
        ok = True
        for section in ("allow", "ask", "deny"):
            a = sorted(actual_claude.get(section, []))
            e = sorted(perm_claude.get(section, []))
            if a != e:
                print(f"[DRIFT] Claude permissions.{section}: {len(a)} actual vs {len(e)} expected")
                aset, eset = set(a), set(e)
                for m in list(eset - aset)[:3]:
                    print(f"  + missing: {m}")
                for m in list(aset - eset)[:3]:
                    print(f"  - extra:   {m}")
                ok = False
        actual_kimi_norm = extract_kimi_blocks(actual_kimi)
        expected_kimi_norm = sorted(b.strip() for b in kimi_blocks.split("\n\n") if b.strip())
        if actual_kimi_norm != expected_kimi_norm:
            print(f"[DRIFT] Kimi [[permission]] blocks: {len(actual_kimi_norm)} actual vs {len(expected_kimi_norm)} expected")
            ok = False
        if ok:
            print("[OK] .claude/settings.json и .kimi-code/config.toml совпадают с .shared/permissions.yaml")
            return 0
        return 1

    # Regenerate
    update_claude_file(perm_claude)
    update_kimi_file(kimi_blocks)
    n_claude = sum(len(v) for v in perm_claude.values())
    n_kimi = kimi_blocks.count("[[permission]]")
    print(f"[SYNC] Claude: {n_claude} rules, Kimi: {n_kimi} rules — regenerated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
