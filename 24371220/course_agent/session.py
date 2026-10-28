"""Task requirements and business tools exposed through the official Tool API."""
import json

from smolagents import Tool

from .evidence import EvidenceStore
from .policy import PYTEST
from .workspace import TOOL_SPECS, WorkspaceTools


EXTRA_TOOLS = {
    'update_plan': ('Set the task plan; preserve titles/order and update todo/doing/done.',
                    {'items': {'type': 'array'}}, ['items']),
    'write_note': ('Save a literal model-written note grounded in previously exposed evidence. Paper notes need section.',
                   {'title': {'type': 'string'}, 'content': {'type': 'string'},
                    'evidence_ids': {'type': 'array'}, 'section': {'type': 'string'}},
                   ['title', 'content', 'evidence_ids']),
    'recall': ('Queue evidence ids; batches are bounded and overflow remains pending.',
               {'evidence_ids': {'type': 'array'}}, ['evidence_ids']),
    'task_status': ('Show remaining reading, notes, changes and verification, plus evidence ids.', {}, []),
}


class CourseTool(Tool):
    skip_forward_signature_validation = True  # Official wrapper-tool extension point.

    def __init__(self, session, name, description, properties, required):
        self.session, self.name, self.description = session, name, description
        self.inputs = {key: {'type': value['type'], 'description': key.replace('_', ' '),
                             **({'nullable': True} if key not in required else {})}
                       for key, value in properties.items()}
        self.output_type = 'object'
        self.parameters = {'type': 'object', 'properties': properties, 'required': required,
                           'additionalProperties': False}
        super().__init__()

    def forward(self, **kwargs):
        arguments = {k: v for k, v in kwargs.items() if v is not None}
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
        self.agent = None
        self.context = None
        self.audit = None
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
        return result

    def status(self, compact=False):
        missing = self.evidence.missing(first_write=not self.writes) if not self.writes or self.contract.profile == 'paper' else []
        versions = self.versions()
        missing += ['baseline: ' + ' '.join(cmd) for cmd in self.contract.verify_commands
                    if tuple(cmd) not in self.baselines]
        missing += ['verify current files: ' + ' '.join(cmd) for cmd in self.contract.verify_commands
                    if self.verified.get(tuple(cmd)) != versions]
        if self.contract.require_write:
            targets = self.contract.editable if self.contract.profile == 'source' else set()
            if targets - self.writes:
                missing.append('remaining source changes: ' + ', '.join(sorted(targets - self.writes)))
            elif not self.writes:
                missing.append('make the requested change')
        if not self.plan or any(item['status'] != 'done' for item in self.plan):
            missing.append('finish all plan items after their work and checks')
        data = {'plan': self.plan, 'remaining': missing, 'changed_files': sorted(self.writes),
                'requests_left': self.contract.max_calls - (self.audit.calls if self.audit else 0),
                'pending_recall': self.evidence.pending[:20],
                'repeated_action_count': self.evidence.repeats,
                'next_step': 'write notes after each batch; then complete changes and verification' if self.contract.profile == 'paper'
                else 'read full files once; summarize complete mechanisms; edit; verify'}
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
        if any(not isinstance(i, dict) or not isinstance(i.get('title'), str) or not i['title'].strip()
               or i.get('status') not in {'todo', 'doing', 'done'} for i in items):
            raise ValueError('Each plan item requires a nonempty title and todo/doing/done status')
        if self.plan and [i['title'] for i in self.plan] != [i['title'] for i in items]:
            raise ValueError('Preserve plan titles and order')
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
        if not self.plan:
            raise ValueError('Establish a plan before editing')
        absent = [cmd for cmd in self.contract.verify_commands if tuple(cmd) not in self.baselines]
        if absent:
            raise ValueError('Run baseline verification before editing: ' + str(absent))
        if not self.writes or self.contract.profile == 'paper':
            missing = self.evidence.missing(first_write=not self.writes)
            if missing:
                raise ValueError('Edit prerequisites: ' + '; '.join(missing))
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
            output = result['stdout'] + result['stderr']
            failures = [line for line in output.splitlines() if line.startswith('FAILED ')]
            self.last_test = {'rc': result['rc'], 'stage_one_passed': bool(self.writes) and
                              not result.get('timed_out') and result['rc'] in (0, 1) and
                              (result['rc'] == 0 or bool(failures)) and
                              all('csv' in line.lower() for line in failures)}

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
        remaining = self.status(compact=True)['remaining']
        if self.two_stage and not self.stage_one_verified:
            remaining.append('intermediate first-subtask verification and plan update')
        if remaining:
            raise ValueError('; '.join(remaining))
        return True

    def task_prompt(self):
        return self.contract.text + '\n\nCourse execution contract:\n' + json.dumps(self.contract.view(), ensure_ascii=False) + '''
Use update_plan before editing, run baseline checks, then read the required files with read_file.
Tools return Python dicts; use their file_hash for expected_hash. Variables persist across actions.
Read original evidence in batches. After each batch, write_note with a literal model-written summary
and its evidence_ids. Notes are source-version-bound; never invent sources or note text.
For source tasks, read_file all three files first, then read/reuse complete mechanisms from all three
before the first edit. A source note may replace original text only after its mechanisms were exposed.
For paper tasks, cover every required page and update five section notes incrementally; section must
be overview/reasoning/tool_use/multi_agent/outlook. After full coverage reuse all five notes together,
write report.json, run the final tests and mark the plan done. Do not keep rereading unchanged pages.
All writes and tests must use these tools. Call final_answer only after current-file verification.
The course checks and task_status share the same prerequisites as the context selector.
'''
