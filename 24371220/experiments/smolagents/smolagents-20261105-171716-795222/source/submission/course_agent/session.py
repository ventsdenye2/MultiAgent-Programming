"""Task requirements and business tools exposed through the official Tool API."""
import json
import ast
import re
import copy
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

COURSE_TOOL_DETAILS = {
    'read_file': " Returns dict: content (text), file_hash, evidence_ids. Read result['content'], not result[:N].",
    'read_range': ' Returns dict: content (text), file_hash, evidence_ids.',
    'read_symbol': ' Returns dict: content (text), file_hash, evidence_ids.',
    'run_command': ' argv is a Python list[str]. Returns dict: rc, stdout (text), stderr, timed_out.',
    'read_pdf': ' Returns dict: pages (list of {page,text}), evidence_ids, delivery. '
                'Extract the required range once; complete pages are sent in bounded batches. '
                'Queued ids are not yet read. Do not print all pages.',
}

COMPACT_TOOL_DETAILS = {
    'write_note': ' Returns dict: note_id, sources, chars.',
    'save_answer': ' answer must contain exactly value. Returns dict: section, question_id, saved.',
    'save_section': ' Returns dict: section, saved.',
    'submit_report': ' Returns dict: ok, path, before_hash, file_hash, changed.',
}

SOURCE_WORKFLOW = '''Read all three files with read_file first, then read/reuse complete mechanisms from all three
before the first edit. Source notes are OPTIONAL; current source blocks can be used directly.
When progress says phase=edit, the initial reading and baseline are satisfied. Apply a scoped edit and verify.
A note may replace original text only after its mechanisms were exposed. Do not repeat full reads to register them again.
'''
PAPER_WORKFLOW = '''Paper: Plan, baseline pytest, read report.json and paper.json, then read_pdf once for the full range. Batches advance automatically; queued pages await delivery. On error an eligible batch may return once, without renewal. Do not print all pages or reread to advance.
Save answers as soon as evidence suffices: save_answer(section, question_id, answer={'value': ...}, evidence_id, page, quote). Include complete exact supporting quotes for every item; matching proves provenance, not semantic support. Save prose with save_section.
Use write_note with delivered evidence IDs for conclusions, pages, method distinctions, limitations and open questions; preserve important facts without repeating long quotes. Recall registered pages with recall_pages(pages=[...]) or evidence IDs with recall. If a later tool fails, keep successful actions and repair only the failure.
After all pages are read and five latest notes appear together in a later request, call submit_report(overview, expected_hash), then final_answer.
Multi-agent collaboration and training are future suggestions, not implemented features.
'''


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

    def compact_code_prompt(self):
        # Derive requiredness and Python defaults from the actual wrapper signature,
        # never from Tool.inputs nullable (which describes a different property).
        args, details = [], []
        types = {'string': 'str', 'integer': 'int', 'number': 'float', 'boolean': 'bool',
                 'array': 'list', 'object': 'dict'}
        for key, parameter in self.call_signature.parameters.items():
            schema = self.parameters['properties'][key]
            detail = json.dumps(schema, ensure_ascii=False, separators=(',', ':'))
            default = '' if parameter.default is Parameter.empty else ' = ' + repr(parameter.default)
            args.append(f'{key}: {types.get(schema.get("type"), "object")}{default}')
            details.append(f'{key}: {detail}')
        description = self.description + COMPACT_TOOL_DETAILS.get(self.name, '')
        doc = description + ('\n' + '\n'.join(details) if details else '')
        # repr produces a valid Python string literal even for arbitrary metadata.
        return f'def {self.name}({", ".join(args)}) -> dict:\n    {doc!r}'


class CourseSession:
    def __init__(self, contract, output, log, config, auto=True):
        self.contract, self.log, self.auto = contract, log, auto
        self.static_context_compact = config.get('static_context_compact', False)
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
        detailed = self.contract.profile in {'source', 'paper'}
        excluded = {'list_files', 'search_code', 'read_range', 'read_symbol', 'replace_text', 'replace_text_batch', 'write_file'} if self.contract.profile == 'paper' else {'read_pdf'}
        if self.contract.profile != 'source': excluded.add('replace_text_batch')
        if self.contract.profile == 'source': excluded.add('replace_text')
        result = [CourseTool(self, name, spec['description'] + (COURSE_TOOL_DETAILS.get(name, '') if detailed else ''), spec['parameters']['properties'],
                             spec['parameters']['required']) for name, spec in TOOL_SPECS.items()
                  if name not in excluded]
        for name, (description, properties, required) in EXTRA_TOOLS.items():
            result.append(CourseTool(self, name, description, properties, required))
        if self.contract.profile == 'paper':
            result.append(CourseTool(self, 'recall_pages',
                                     'Queue registered paper pages for original text; delivery is bounded and may remain pending.',
                                     {'pages': {'type': 'array', 'items': {'type': 'integer'},
                                                'description': 'List of registered page numbers.'}}, ['pages']))
            specs = {
                'save_answer': ('Save an answer with exact cited page text.', {'section': {'type':'string'}, 'question_id': {'type':'string'}, 'answer': {'type':'object', 'description':"{'value': string, integer or list of strings}"}, 'evidence_id': {'type':'string'}, 'page': {'type':'integer'}, 'quote': {'type':'string'}}),
                'save_section': ('Save section prose.', {'section': {'type':'string'}, 'summary': {'type':'string'}, 'application': {'type':'string'}}),
                'submit_report': ('Serialize saved results to report.json.', {'overview': {'type':'string'}, 'expected_hash': {'type':'string'}}),
            }
            for name, (description, properties) in specs.items():
                result.append(CourseTool(self, name, description, properties, list(properties)))
        paper = self.contract.profile == 'paper'
        note_properties = {
            'title': {'type': 'string', 'description': 'Stable note title; reuse it when updating the same note.'},
            'content': {'type': 'string', 'description':
                        f'One contiguous string literal, 20..{1500 if paper else 3000} characters. '
                        'No adjacent string fragments, concatenation or variable; text must occur verbatim in your response.'},
            'evidence_ids': {'type': 'array', 'items': {'type': 'string'}, 'description':
                             "Python list[str], e.g. ['ev-abc'], not a string. Copy ids from delivered Evidence headers."
                             if detailed else 'Ids of current-version originals already sent to you.'},
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

    def progress(self, sending=False):
        """One state snapshot; presentation and completion use the same facts."""
        missing = self.evidence.missing(first_write=not self.writes) if not self.writes or self.contract.profile == 'paper' else []
        versions = self.versions()
        commands = tuple(tuple(cmd) for cmd in self.contract.verify_commands)
        unverified = tuple(cmd for cmd in commands if self.verified.get(cmd) != versions)
        targets = self.contract.editable if self.contract.require_write and self.contract.profile == 'source' else set()
        completion_missing = []
        if self.two_stage and not self.stage_one_verified:
            completion_missing.append('intermediate first-subtask verification and plan update')
        if self.contract.profile == 'paper' and self.writes:
            try:
                _, content, _ = self.workspace._read('report.json')
                report = json.loads(content)
                if report != self.evidence.report(report['overview']): raise ValueError('report differs from saved results')
            except (ValueError, KeyError, TypeError, OSError):
                completion_missing.append('submit report from current saved answers and evidence')
        return TaskProgress(
            plan=tuple((i['title'], i['status']) for i in self.plan),
            evidence_missing=tuple(missing),
            baseline_missing=tuple(cmd for cmd in commands if cmd not in self.baselines),
            changes_missing=tuple(sorted(targets - self.writes)),
            require_change=self.contract.require_write and not self.writes,
            verification_missing=unverified, changed_files=tuple(sorted(self.writes)),
            baseline_done=len(self.baselines), verified_current=len(commands)-len(unverified),
            required_checks=len(commands),
            requests_left=max(0, self.contract.max_calls-(self.audit.calls if self.audit else 0)-int(sending)),
            completion_missing=tuple(completion_missing),
            final_completes_plan=self.contract.profile in {'source', 'paper'})

    def progress_token(self):
        """Material progress for the run monitor; plan churn alone is not work."""
        return json.dumps({
            'reads':self.evidence.full_reads, 'exposed':sorted(self.evidence.exposed),
            'ranges':self.evidence.received_ranges, 'notes':self.evidence.notes,
            'answers':self.evidence.answers, 'section_text':self.evidence.section_text,
            'writes':self.written_versions, 'baselines':sorted(self.baselines),
            'verified':sorted((list(cmd), versions) for cmd,versions in self.verified.items()),
            'ready':self.progress().ready_for_final,
        }, ensure_ascii=False, sort_keys=True)

    def status(self, compact=False):
        data = {**self.progress().status(), 'pending_recall': self.evidence.pending[:20],
                'repeated_action_count': self.evidence.repeats,
                'next_step': 'read page batches, update relevant topic notes, then complete the report and verification' if self.contract.profile == 'paper'
                else 'read full files once; use the original mechanisms or optional notes; edit; verify'}
        if self.audit and self.audit.last_classification not in {None, 'ok'}:
            data['last_response_classification'] = self.audit.last_classification
            data['response_recovery'] = 'Previous body was empty or truncated; produce one complete valid action within the configured output budget.'
        if self.evidence.repeats >= 2:
            data['stalled'] = 'Repeated unchanged action. Use the missing items above; inspect recent error and pending evidence.'
        if not compact:
            data['evidence'] = self.evidence.catalog()
            data['notes'] = self.evidence.notes
            if self.contract.profile == 'paper':
                data['answers'] = copy.deepcopy(self.evidence.answers)
                data['section_text'] = copy.deepcopy(self.evidence.section_text)
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

    def _record_command(self, args, result, before_versions=None):
        command = tuple(args['argv'])
        if command not in {tuple(x) for x in self.contract.verify_commands}:
            return
        self.verified.pop(command, None)
        self.last_test = None
        self.log('verification_result', command=list(command), rc=result['rc'],
                 before_versions=before_versions, after_versions=self.versions(),
                 timed_out=result.get('timed_out', False))
        if before_versions is not None and before_versions != self.versions():
            self.log('verification_invalidated', command=list(command), before_versions=before_versions, after_versions=self.versions())
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
            self.last_test = {'rc': result['rc'], 'versions': self.versions(), 'stage_one_passed': bool(self.writes) and
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
            elif name == 'save_answer':
                answer = args['answer']
                if type(answer) is not dict or set(answer) != {'value'}: raise ValueError('answer must have exactly one value key')
                result = self.evidence.save_answer(args['section'], args['question_id'], answer['value'], args['evidence_id'], args['page'], args['quote'])
            elif name == 'save_section':
                result = self.evidence.save_section(**args)
            elif name == 'submit_report':
                content = json.dumps(self.evidence.report(args['overview']), ensure_ascii=False, indent=2) + '\n'
                result = self.invoke('write_file', {'path': 'report.json', 'content': content, 'expected_hash': args['expected_hash']})
            elif name == 'recall':
                result = self.evidence.recall(args['evidence_ids'])
            elif name == 'recall_pages' and self.contract.profile == 'paper':
                result = self.evidence.recall_pages(args['pages'])
            elif name == 'task_status':
                result = self.status()
            else:
                command_versions = None
                if name in {'write_file', 'replace_text', 'replace_text_batch'}:
                    self._before_write(args)
                elif name == 'run_command':
                    self._confirm(name, args)
                    command_versions = self.versions()
                result = self.workspace.invoke(name, args)
                if name in {'write_file', 'replace_text', 'replace_text_batch'} and result.get('changed'):
                    self.writes.add(result['path'])
                    self.written_versions[result['path']] = result['file_hash']
                    self.verified.clear()
                    self.last_test = None
                    self.evidence.invalidate(result['path'], result['file_hash'])
                if name == 'run_command':
                    self._record_command(args, result, command_versions)
            result = self.evidence.observe(name, args, result)
            self.log('tool_result', action={'tool': name, **args}, result=result)
            return result
        except Exception as exc:
            self.log('tool_error', tool=name, error_type=type(exc).__name__, error=str(exc))
            raise

    def check_final(self, answer, memory, agent=None):
        if self.contract.profile in {'source', 'paper'}:
            progress = self.progress()
            blockers = list(progress.evidence_missing) + list(progress.baseline_missing) + list(progress.changes_missing) + list(progress.completion_missing)
            if progress.require_change: blockers.append('make the requested change')
            if blockers: raise ValueError('; '.join(map(str, blockers)))
            for command in progress.verification_missing:
                result = self.invoke('run_command', {'argv': list(command)})
                if result['rc'] != 0 or result.get('timed_out'):
                    raise ValueError('Verification failed; repair the issue: ' + result['stdout'][-3000:] + result['stderr'][-3000:])
            if self.progress().work_complete and self.plan:
                self._plan([{**item, 'status': 'done'} for item in self.plan])
        remaining = self.progress().remaining
        if remaining:
            raise ValueError('; '.join(remaining))
        return True

    def task_prompt(self):
        if self.static_context_compact and self.contract.profile in {'source', 'paper'}:
            return self._compact_task_prompt()
        instructions = '''
Use update_plan before editing, run baseline checks, then read the required files with read_file.
Tools return Python dicts; use their file_hash for expected_hash. Variables persist across actions.
Do not reset a successful plan or repeat completed baseline checks. Continue the next unfinished action.
All writes and tests must use these tools.
'''
        if self.contract.profile not in {'source', 'paper'}:
            instructions += 'Call final_answer only after current-file verification.\n'
        # The official system prompt already renders the actual import list.
        # Keep the task-specific capability boundary concise to preserve the
        # basic assignment's much smaller context budget.
        instructions += ('os and pathlib are unavailable in action code; use file/command tools. '
                         'Import allowed modules before using them.\n')
        if self.agent._use_structured_outputs_internally:
            instructions += ('When calling write_note, put the complete exact note text in the thought field, '
                             'then pass that same text as one content string literal in code. This preserves '
                             'a contiguous model-authored copy through JSON/Python escaping.\n')
        elif self.contract.profile in {'source', 'paper'}:
            instructions += ('When calling write_note, include its complete exact content in the prose before the code '
                             'and pass the same text as one content string literal.\n')
        if self.contract.profile == 'source':
            instructions += SOURCE_WORKFLOW
        elif self.contract.profile == 'paper':
            instructions += PAPER_WORKFLOW
        return (self.contract.text + '\n\nCourse execution contract:\n' +
                json.dumps(self.contract.view(), ensure_ascii=False) + instructions)

    def _compact_task_prompt(self):
        instructions = ('\nUse update_plan before editing and run baseline checks. '
                        'os and pathlib are unavailable in action code.\n')
        if self.agent._use_structured_outputs_internally:
            instructions += ('For write_note, put the complete exact note text in thought and pass the same text '
                             'as one content string literal in code.\n')
        else:
            instructions += ('For write_note, include its complete exact content in the prose before the code '
                             'and pass the same text as one content string literal.\n')
        if self.contract.profile == 'source':
            instructions += SOURCE_WORKFLOW
        else:
            instructions += PAPER_WORKFLOW
        return (self.contract.text + '\n\nCourse execution contract:\n' +
                json.dumps(self.contract.view(), ensure_ascii=False) + instructions)
