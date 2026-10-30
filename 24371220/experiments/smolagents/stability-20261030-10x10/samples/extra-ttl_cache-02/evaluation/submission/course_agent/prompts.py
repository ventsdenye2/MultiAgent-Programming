"""Course prompts configured through upstream's public prompt_templates API."""
import importlib.resources

import yaml


JSON_PROTOCOL = '''Return ONE JSON object with string fields "thought" (next action) and "code" (executable Python), then STOP.
Example: {"thought":"Check progress.","code":"print(task_status())"}
No Markdown fences, extra JSON, simulated observations or future turns. Keep the action within the output budget.
'''

PYTHON_PROTOCOL = '''Briefly describe the next action, then output ONE fenced Python block and STOP after it.
Example:
Read the current progress.
```python
print(task_status())
```
Do not emit JSON wrappers, simulated tool output or future conversation turns. Keep the action within the output budget.
'''

SYSTEM = '''Complete the task using the Python tools below.
__OUTPUT_PROTOCOL__

Call tools with keyword arguments. Arrays are Python lists ['a','b'], never encoded strings.
Reads return dicts: r['content'] is text, r['file_hash'] is the edit hash. Commands return r['rc'] and r['stdout'].
Use print() for needed output. Group independent operations. Variables and imports persist; successful statements
before an error remain executed. Correct the error without restarting completed work.

Paths are relative to the task repository; '.' is its root. Omit cwd for commands there.
Use tools for all file/command operations. Edit only allowed files, never tests. Use current file_hash as expected_hash.
Prefer unique replace_text edits to long file rewrites. Imports allowed: {{authorized_imports}}; import before use.
Read sufficient evidence, preserve relevant findings when useful, implement and verify. Avoid repeated unchanged reads.
Call final_answer only after the requested artifact and required checks are complete.
When the current action runs a required test, inspect its actual rc; if it succeeds, update the existing plan
and call final_answer in the same action when all requirements are satisfied. If it fails, fix the failure instead.

Available tools:
```python
{%- for tool in tools.values() %}
{{ tool.to_code_prompt() }}
{% endfor %}
```
{%- if custom_instructions %}
{{custom_instructions}}
{%- endif %}
'''


def course_prompt_templates(structured=True):
    templates = yaml.safe_load(importlib.resources.files('smolagents.prompts')
                               .joinpath('structured_code_agent.yaml' if structured else 'code_agent.yaml').read_text())
    templates['system_prompt'] = SYSTEM.replace('__OUTPUT_PROTOCOL__', JSON_PROTOCOL if structured else PYTHON_PROTOCOL)
    return templates
