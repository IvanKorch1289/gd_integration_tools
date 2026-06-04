"""Diagnostic: compare original (HEAD) vs current __init__.py for missing bool fields."""
import re
import subprocess
from pathlib import Path

result = subprocess.run(
    ['git', 'show', 'HEAD:src/backend/core/config/features/__init__.py'],
    capture_output=True, text=True, check=True, cwd='/home/user/dev/gd_integration_tools',
)
orig_text = result.stdout
cur_text = Path('/home/user/dev/gd_integration_tools/src/backend/core/config/features/__init__.py').read_text()

orig = re.findall(r'^\s+(\w+):\s+bool', orig_text, re.MULTILINE)
cur = re.findall(r'^\s+(\w+):\s+bool', cur_text, re.MULTILINE)
print(f'Original (HEAD): {len(orig)} fields')
print(f'Current: {len(cur)} fields')
print(f'Delta: {len(orig) - len(cur)}')
removed = set(orig) - set(cur)
print(f'\nRemoved from __init__.py: {len(removed)} fields')
for f in sorted(removed):
    print(f'  - {f}')

expected = {'presidio_pii_enabled', 'nemo_guardrails_enabled', 'langgraph_checkpointer_enabled',
            'ai_gateway_enforce', 'ai_policy_enforce', 'ai_pii_tokenizer_enabled',
            'ai_prompt_sweep_strict', 'ai_prompt_eval_blocking', 'ai_skill_toml_enabled',
            'ai_agent_dsl_enabled', 'mcp_gateway_namespaces_enabled',
            'ai_audit_unified_enabled', 'workflow_invoke_agent_enabled'}
unexpected = removed - expected
print(f'\nUnexpected extra removed: {len(unexpected)}')
for f in sorted(unexpected):
    print(f'  - {f}')

new_text = Path('/home/user/dev/gd_integration_tools/src/backend/core/config/features/sprints_24_27.py').read_text()
new_fields = set(re.findall(r'^\s+(\w+):\s+bool', new_text, re.MULTILINE))
missing = expected - new_fields
print(f'\nMissing from new file: {missing or "none"}')
