#!/usr/bin/env python3
"""Удалить sys.path manipulation из всех страниц."""

from __future__ import annotations

import re
from pathlib import Path

PAGES = Path("src/frontend/streamlit_app/pages")

# Файлы где нужно просто удалить sys.path блок (3-4 строки)
REMOVE_BLOCK = {
    "04_Onboarding.py",
    "10_Orders.py",
    "11_Routes.py",
    "12_Logs.py",
    "13_Cron_Builder.py",
    "15_Workflow_Cost_Estimation.py",
    "18_Workflow_Versioning.py",
    "19_Saga_Compensation_Viewer.py",
    "20_AI_Chat.py",
    "21_AI_Feedback.py",
    "30_DSL_Playground.py",
    "32_DSL_Builder.py",
    "33_DSL_Templates.py",
    "44_DSL_Diff_History.py",
    "45_admin.py",
    "46_DSL_DryRun.py",
    "47_AI_Safety.py",
    "48_Prompt_Lab.py",
    "50_Feature_Flags.py",
    "52_Resilience.py",
    "53_Queue_Monitor.py",
    "54_DLQ_Replay.py",
    "55_Pool_Monitor.py",
    "56_Processes.py",
    "58_Action_Bus.py",
    "59_S3_Files.py",
    "60_Cache_Explorer.py",
    "61_Audit_Log.py",
    "62_Schema_Registry.py",
    "64_SQL_Admin.py",
    "65_Services.py",
    "66_Workflow_Logs.py",
    "67_Jobs.py",
    "68_Plugin_Marketplace.py",
    "69_Workflow_Live_Logs.py",
    "70_Tenants.py",
    "71_Capabilities.py",
    "72_HITL_Panel.py",
    "73_Config_Viewer.py",
    "76_Plugin_Onboarding.py",
    "82_Tenant_Feature_Flags.py",
    "83_Tenant_Inspection.py",
}

# Файлы с другим именем переменной (_project_root вместо _root)
ALT_NAMES = {
    "45_admin.py": "_project_root",
    "52_Resilience.py": "_project_root",
    "54_DLQ_Replay.py": "_project_root",
    "58_Action_Bus.py": "_project_root",
    "59_S3_Files.py": "_project_root",
    "66_Workflow_Logs.py": "_project_root",
    "69_Workflow_Live_Logs.py": "_project_root",
}

# sys.path паттерн
SYSPATH_PATTERNS = [
    # Standard _root
    re.compile(
        r"\n_root = Path\(__file__\)\.resolve\(\)\.parents\[4\]\n"
        r"if str\(_root\) not in sys\.path:\n"
        r"    sys\.path\.insert\(0, str\(_root\)\)\n"
    ),
    # _project_root variant
    re.compile(
        r"\n_project_root = Path\(__file__\)\.resolve\(\)\.parents\[4\]\n"
        r"if str\(_project_root\) not in sys\.path:\n"
        r"    sys\.path\.insert\(0, str\(_project_root\)\)\n"
    ),
]


def fix_file(path: Path) -> bool:
    """Удалить sys.path блок из файла. Returns True if modified."""
    text = path.read_text()

    # Remove sys.path manipulation and the unused import
    new_text = re.sub(r"\nimport sys\n(?=from pathlib import Path\n)", "\n", text)
    new_text = re.sub(r"\nfrom pathlib import Path\n", "\n", new_text)
    for pattern in SYSPATH_PATTERNS:
        new_text = pattern.sub("\n", new_text)

    if new_text != text:
        path.write_text(new_text)
        return True
    return False


def main() -> None:
    modified = []
    for name in sorted(PAGES.glob("*.py")):
        if name.name == "00_Home.py":
            continue  # app.py's sys.path is fine
        if name.name in REMOVE_BLOCK or any(
            name.name.startswith(p)
            for p in (
                "04_",
                "10_",
                "11_",
                "12_",
                "13_",
                "14_",
                "15_",
                "16_",
                "17_",
                "18_",
                "19_",
                "20_",
                "21_",
                "22_",
                "23_",
                "24_",
                "25_",
                "26_",
                "27_",
                "28_",
                "29_",
                "30_",
                "31_",
                "32_",
                "33_",
                "34_",
                "35_",
                "36_",
                "37_",
                "38_",
                "39_",
                "40_",
                "41_",
                "42_",
                "43_",
                "44_",
                "45_",
                "46_",
                "47_",
                "48_",
                "49_",
                "50_",
                "51_",
                "52_",
                "53_",
                "54_",
                "55_",
                "56_",
                "57_",
                "58_",
                "59_",
                "60_",
                "61_",
                "62_",
                "63_",
                "64_",
                "65_",
                "66_",
                "67_",
                "68_",
                "69_",
                "70_",
                "71_",
                "72_",
                "73_",
                "74_",
                "75_",
                "76_",
                "77_",
                "78_",
                "79_",
                "80_",
                "81_",
                "82_",
                "83_",
                "85_",
            )
        ):
            if name.name != "31_DSL_Visual_Editor.py":  # already deleted
                if fix_file(name):
                    modified.append(name.name)

    print(f"Modified {len(modified)} files:")
    for f in modified:
        print(f"  - {f}")


if __name__ == "__main__":
    main()
