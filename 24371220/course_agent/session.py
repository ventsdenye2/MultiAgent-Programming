"""Task requirements and business tools exposed through the official Tool API."""
import json
import ast
import re
from inspect import Parameter, Signature

from smolagents import Tool

from .evidence import EvidenceStore
from .policy import PYTEST
from .progress import TaskProgress
from .workspace import TOOL_SPECS, WorkspaceTools


EXTRA_TOOLS = {
    'update_plan': ('Set the task plan; preserve titles/order and update todo/doing/done.',
                    {'items': {'type': 'array', 'description':
                               'List of objects, e.g. [{"title":"Read sources","status":"doing"}]. '
                               'Each status is todo, doing or done; retain existing titles/order.'}}, ['items']),
    'recall': ('Queue evidence ids; batches are bounded and overflow remains pending.',
               {'evidence_ids': {'type': 'array'}}, ['evidence_ids']),
    'task_status': ('Show the current plan, remaining reading, notes, changes and verification, plus evidence ids.', {}, []),
}


class CourseTool(Tool):
    skip_forward_signature_validation = True  # Official wrapper-tool extension point.

    def __init__(self, session, name, description, properties, required):
        self.session, self.name, self.description = session, name, description
        self.inputs = {key: {'type': value['type'], 'description': value.get('description', key.replace('_', ' ')),
                             **({'nullable': True} if key not in required else {})}
                       for key, value in properties.items()}
        self.output_type = 'object'
        self.parameters = {'type': 'object', 'properties': properties, 'required': required,
                           'additionalProperties': False}
        self.call_signature = Signature([
            Parameter(key, Parameter.POSITIONAL_OR_KEYWORD,
                      default=Parameter.empty if key in required else None)
            for key in self.inputs
        ])
        super().__init__()

    def forward(self, *args, **kwargs):
        # Use Python's binding rules for the same signature exposed by Tool.
        bound = self.call_signature.bind(*args, **kwargs)
        arguments = {k:v for k,v in bound.arguments.items() if v is not None}
        WorkspaceTools._validate_schema_value(arguments, self.parameters)
        return self.session.invoke(self.name, arguments)


class CourseSession:
    def __init__(self, contract, output, log, config, auto=True):
        self.contract, self.log, self.auto = contract, log, auto
        self.workspace = WorkspaceTools(contract.repo, output, contract.editable, log,
                                        command_rules=contract.verify_commands,
                                        command_timeout=config.get('command_timeout', 120),
                                        key_env=config.get('key_env', ''))
        self.evidence = EvidenceStore(contract, self.workspace, log)
        self.plan = []
        self.baselines = set()
        self.verified = {}
        self.writes = set()
        self.written_versions = {}
        self.agent = None
        self.context = None
        self.audit = None
        self.progress_monitor = None
        self.last_test = None
        self.two_stage = contract.profile == 'basic' and '净额' in contract.text and 'CSV' in contract.text
        self.stage_one_verified = False
        self._baseline_snapshot = self.versions()

    def versions(self):
        return {path: self.workspace.current_hash(path) for path in sorted(self.contract.editable)}

    def tools(self):
        result = [CourseTool(self, name, spec['description'], spec['parameters']['properties'],
                             spec['parameters']['required']) for name, spec in TOOL_SPECS.items()
                  if name != 'read_pdf' or self.contract.profile == 'paper']
        for name, (description, properties, required) in EXTRA_TOOLS.items():
            result.append(CourseTool(self, name, description, properties, required))
        paper = self.contract.profile == 'paper'
        note_properties = {
            'title': {'type': 'string', 'description': 'Stable note title; reuse it when updating the same note.'},
            'content': {'type': 'string', 'description':
                        f'One contiguous string literal, 20..{1500 if paper else 3000} characters. '
                        'No adjacent string fragments, concatenation or variable; text must occur verbatim in your response.'},
            'evidence_ids': {'type': 'array', 'description': 'Ids of current-version originals already sent to you.'},
        }
        note_required = ['title', 'content', 'evidence_ids']
        if paper:
            note_properties['section'] = {'type': 'string', 'description': 'Required topic: ' + '/'.join(self.contract.topics)}
            note_required.append('section')
        else:
            note_properties['section'] = {'type': 'string', 'description': 'Optional stable note key; source notes still allow 20..3000 characters.'}
        result.append(CourseTool(self, 'write_note',
                                 'Save or update a literal model-written note grounded in exposed evidence.',
                                 note_properties, note_required))
        return result

    def progress(self):
        """One state snapshot; presentation and completion use the same facts."""
        missing = self.evidence.missing(first_write=not self.writes) if not self.writes or self.contract.profile == 'paper' else []
        versions = self.versions()
        commands = tuple(tuple(cmd) for cmd in self.contract.verify_commands)
        unverified = tuple(cmd for cmd in commands if self.verified.get(cmd) != versions)
        targets = self.contract.editable if self.contract.require_write and self.contract.profile == 'source' else set()
        return TaskProgress(
            plan=tuple((i['title'], i['status']) for i in self.plan),
            evidence_missing=tuple(missing),
            baseline_missing=tuple(cmd for cmd in commands if cmd not in self.baselines),
            changes_missing=tuple(sorted(targets - self.writes)),
            require_change=self.contract.require_write and not self.writes,
            verification_missing=unverified, changed_files=tuple(sorted(self.writes)),
            baseline_done=len(self.baselines), verified_current=len(commands)-len(unverified),
            required_checks=len(commands),
            requests_left=self.contract.max_calls-(self.audit.calls if self.audit else 0),
            completion_missing=('intermediate first-subtask verification and plan update',)
            if self.two_stage and not self.stage_one_verified else ())

    def progress_token(self):
        """Material progress for the run monitor; plan churn alone is not work."""
        return json.dumps({
            'reads':self.evidence.full_reads, 'exposed':sorted(self.evidence.exposed),
            'ranges':self.evidence.received_ranges, 'notes':self.evidence.notes,
            'writes':self.written_versions, 'baselines':sorted(self.baselines),
            'verified':sorted((list(cmd), versions) for cmd,versions in self.verified.items()),
            'ready':self.progress().ready_for_final,
        }, ensure_ascii=False, sort_keys=True)

    def status(self, compact=False):
        data = {**self.progress().status(), 'pending_recall': self.evidence.pending[:20],
                'repeated_action_count': self.evidence.repeats,
                'next_step': 'write notes after each batch; then complete changes and verification' if self.contract.profile == 'paper'
                else 'read full files once; summarize complete mechanisms; edit; verify'}
        if self.audit and self.audit.last_classification not in {None, 'ok'}:
            data['last_response_classification'] = self.audit.last_classification
            data['response_recovery'] = 'Previous body was empty or truncated; produce a complete valid code action within 4096 output tokens.'
        if self.evidence.repeats >= 2:
            data['stalled'] = 'Repeated unchanged action. Use the missing items above; inspect recent error and pending evidence.'
        if not compact:
            data['evidence'] = self.evidence.catalog()
            data['notes'] = self.evidence.notes
        return data

    def _confirm(self, name, args):
        if self.auto:
            return
        from smolagents.memory import TaskStep
        print(json.dumps({'tool': name, 'arguments': args}, ensure_ascii=False, indent=2))
        while True:
            reply = input('y 确认 / n 拒绝 /status /add 指令 /quit: ').strip()
            if reply == '/quit':
                raise KeyboardInterrupt
            if reply == '/status':
                print(json.dumps(self.status(), ensure_ascii=False, indent=2))
            elif reply.startswith('/add '):
                self.log('user_instruction', content=reply[5:])
                self.agent.memory.steps.append(TaskStep(reply[5:]))
                raise ValueError('User added instructions; review before proceeding')
            elif reply.lower() == 'n':
                raise ValueError('User declined this action')
            elif reply.lower() == 'y':
                return

    def _plan(self, items):
        if not isinstance(items, list) or not 1 <= len(items) <= 10:
            raise ValueError('Plan must contain 1..10 items')
        if self.two_stage and len(items) < 2:
            raise ValueError('This task requires net calculation and CSV export as two ordered plan items')
        if any(not isinstance(i, dict) or not isinstance(i.get('title'), str) or not i['title'].strip()
               or i.get('status') not in {'todo', 'doing', 'done'} for i in items):
            raise ValueError('Each plan item requires a nonempty title and todo/doing/done status')
        if self.plan and [i['title'] for i in self.plan] != [i['title'] for i in items]:
            raise ValueError("Preserve plan titles and order. Retrieve items = task_status()['plan']; "
                             "change only each item's status, then call update_plan(items=items).")
        if self.two_stage and self.plan and self.plan[0]['status'] != 'done' and items[0]['status'] == 'done':
            if not self.writes or not self.last_test:
                raise ValueError('Run the intermediate full test after the first subtask before marking it done')
            if not self.last_test.get('stage_one_passed'):
                raise ValueError('Intermediate tests must show no remaining first-subtask failures')
            self.stage_one_verified = True
        self.plan = [dict(i) for i in items]
        self.log('plan', items=self.plan)
        return {'items': self.plan}

    def _before_write(self, args):
        progress = self.progress()
        if not progress.plan:
            raise ValueError('Establish a plan before editing')
        if progress.baseline_missing:
            raise ValueError('Run baseline verification before editing: ' + str(progress.baseline_missing))
        if progress.evidence_missing:
            raise ValueError('Edit prerequisites: ' + '; '.join(progress.evidence_missing))
        if self.contract.profile in {'basic', 'generic'}:
            target = self.workspace._norm_rel(args['path'])
            current = self.workspace.current_hash(target)
            if current != 'missing' and self.written_versions.get(target) != current:
                if self.evidence.full_reads.get(target) != current:
                    raise ValueError('Read the current target file before editing: ' + target)
                if not self.evidence.file_exposed(target):
                    raise ValueError('Target source is waiting to be sent; continue pending evidence: ' + target)
        if self.two_stage and not self.stage_one_verified:
            proposed = args.get('content')
            if proposed is None and 'old_text' in args:
                _, current, _ = self.workspace._read(args['path'])
                proposed = current.replace(args['old_text'], args['new_text'])
            try:
                tree = ast.parse(proposed or '')
            except SyntaxError:
                tree = ast.Module(body=[], type_ignores=[])
            if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'export_csv'
                   for n in ast.walk(tree)):
                raise ValueError('Verify the net-only change with full pytest and mark the first plan item done before CSV export')
        self._confirm('write', args)

    def _record_command(self, args, result):
        command = tuple(args['argv'])
        if command not in {tuple(x) for x in self.contract.verify_commands}:
            return
        if not result.get('timed_out') and result['rc'] in (0, 1):
            if not self.writes and self.versions() == self._baseline_snapshot:
                self.baselines.add(command)
            if result['rc'] == 0:
                self.verified[command] = self.versions()
        if list(command) == PYTEST:
            output = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', result['stdout'] + result['stderr'])
            failures = re.findall(r'^FAILED (.+?)(?: - |$)', output, re.M)
            summaries = re.findall(r'^(?:=+\s*)?(\d+ \w+(?:, \d+ \w+)*) in [\d.]+s\b.*$', output, re.M)
            counts = {name: int(n) for n, name in re.findall(r'(\d+) (\w+)', summaries[-1])} if summaries else {}
            self.last_test = {'rc': result['rc'], 'stage_one_passed': bool(self.writes) and
                              not result.get('timed_out') and result['rc'] == 1 and
                              set(counts) <= {'passed', 'failed', 'warning', 'warnings'} and
                              counts.get('passed', 0) >= 2 and
                              counts.get('passed', 0) + counts.get('failed', 0) == 10 and
                              len(set(failures)) == counts.get('failed', 0) and
                              not any(test in line for line in failures
                                      for test in ('test_summarize_net', 'test_summarize_empty'))}

    def invoke(self, name, args):
        self.log('tool_call', tool=name, arguments=args)
        try:
            if self.audit:
                if self.audit.stop_reason:
                    raise ValueError(self.audit.stop_reason)
            if name == 'update_plan':
                result = self._plan(args['items'])
            elif name == 'write_note':
                result = self.evidence.write_note(**args)
            elif name == 'recall':
                result = self.evidence.recall(args['evidence_ids'], self.context.capacity if self.context else 12000)
            elif name == 'task_status':
                result = self.status()
            else:
                if name in {'write_file', 'replace_text'}:
                    self._before_write(args)
                elif name == 'run_command':
                    self._confirm(name, args)
                result = self.workspace.invoke(name, args)
                if name in {'write_file', 'replace_text'} and result.get('changed'):
                    self.writes.add(result['path'])
                    self.written_versions[result['path']] = result['file_hash']
                    self.verified.clear()
                    self.last_test = None
                    self.evidence.invalidate(result['path'], result['file_hash'])
                if name == 'run_command':
                    self._record_command(args, result)
            result = self.evidence.observe(name, args, result)
            self.log('tool_result', action={'tool': name, **args}, result=result)
            return result
        except Exception as exc:
            self.log('tool_error', tool=name, error_type=type(exc).__name__, error=str(exc))
            raise

    def check_final(self, answer, memory, agent=None):
        remaining = self.progress().remaining
        if remaining:
            raise ValueError('; '.join(remaining))
        return True

    def task_prompt(self):
        instructions = '''
Use update_plan before editing, run baseline checks, then read the required files with read_file.
Tools return Python dicts; use their file_hash for expected_hash. Variables persist across actions.
Do not reset a successful plan or repeat completed baseline checks. Continue the next unfinished action.
All writes and tests must use these tools. Call final_answer only after current-file verification.
'''
        # The official system prompt already renders the actual import list.
        # Keep the task-specific capability boundary concise to preserve the
        # basic assignment's much smaller context budget.
        instructions += ('os and pathlib are unavailable in action code; use file/command tools. '
                         'Import allowed modules before using them.\n')
        if self.agent._use_structured_outputs_internally:
            instructions += ('When calling write_note, put the complete exact note text in the thought field, '
                             'then pass that same text as one content string literal in code. This preserves '
                             'a contiguous model-authored copy through JSON/Python escaping.\n')
        if self.contract.profile in {'source', 'paper'}:
            instructions += '''Read original evidence in batches. After each batch, write_note with a literal model-written summary
and its evidence_ids. Notes are source-version-bound; never invent sources or note text.
'''
        if self.contract.profile == 'source':
            instructions += '''Read all three files with read_file first, then read/reuse complete mechanisms from all three
before the first edit. A source note may replace original text only after its mechanisms were exposed.
'''
        elif self.contract.profile == 'paper':
            instructions += '''Cover every required page and update five section notes incrementally; section must be
overview/reasoning/tool_use/multi_agent/outlook. After full coverage reuse all five notes together,
write report.json, run the final tests and mark the plan done. Do not reread unchanged pages.
'''
        return (self.contract.text + '\n\nCourse execution contract:\n' +
                json.dumps(self.contract.view(), ensure_ascii=False) + instructions)
