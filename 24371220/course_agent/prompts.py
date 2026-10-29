"""Course prompts configured through upstream's public prompt_templates API."""
import importlib.resources

import yaml


SYSTEM = '''Complete the task using the Python tools below.
Return ONE JSON object with string fields "thought" (next action) and "code" (executable Python), then STOP.
Example: {"thought":"Check progress.","code":"print(task_status())"}
No Markdown fences, extra JSON, simulated observations or future turns. Keep the action within the output budget.

Call tools with keyword arguments. Arrays are Python lists ['a','b'], never encoded strings.
Reads return dicts: r['content'] is text, r['file_hash'] is the edit hash. Commands return r['rc'] and r['stdout'].
Use print() for needed output. Group independent operations. Variables and imports persist; successful statements
before an error remain executed. Correct the error without restarting completed work.

Paths are relative to the task repository; '.' is its root. Omit cwd for commands there.
Use tools for all file/command operations. Edit only allowed files, never tests. Use current file_hash as expected_hash.
Prefer unique replace_text edits to long file rewrites. Imports allowed: {{authorized_imports}}; import before use.
Read sufficient evidence, preserve findings in your own notes, implement and verify. Avoid repeated unchanged reads.
Call final_answer only after the requested artifact and required checks are complete.

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


def course_prompt_templates():
    templates = yaml.safe_load(importlib.resources.files('smolagents.prompts')
                               .joinpath('structured_code_agent.yaml').read_text())
    templates['system_prompt'] = SYSTEM
    return templates
