"""Versioned evidence and model-authored notes, independent of AgentMemory."""
from dataclasses import asdict, dataclass
import ast
import hashlib
import json

from .audit import contains


SOURCE_UNITS = {
    "deepinfer/environ.py": {"EnvVar", "rearm", "rearm_all"},
    "deepinfer/logger.py": {"NewLineFormatter", "_setup_logger", "init_logger"},
    "deepinfer/engine/stats_logger.py": {"_log_worker", "_emit_logs"},
}


@dataclass
class Evidence:
    id: str
    source: str
    version: str
    locator: str
    text: str
    required: bool = False
    page: int | None = None
    valid: bool = True
    atomic: bool = False


class EvidenceStore:
    def __init__(self, contract, workspace, log):
        self.contract, self.workspace, self.log = contract, workspace, log
        self.items = {}
        self.full_reads = {}
        self.full_read_ids = {}
        self.required = {}
        self.exposed = set()
        self.current = set()
        self.notes = {}
        self.current_notes = set()
        self.pending = []
        self.last_response = None
        self.raw_texts = set()
        self.recent_results = []
        self.repeats = 0
        self._signature = None
        self.request_number = 0
        self.received_ranges = {}
        self.recall_ranges = {}
        self.offered = []

    def _add(self, source, version, locator, text, required=False, page=None, atomic=False):
        key = hashlib.sha256((source + '\0' + version + '\0' + locator).encode()).hexdigest()[:20]
        eid = 'ev-' + key
        if eid not in self.items:
            item = Evidence(eid, source, version, locator, text, required, page, atomic=atomic)
            self.items[eid] = item
            self.log('evidence', **asdict(item))
        self.raw_texts.add(text)
        if required:
            self.required.setdefault(source, set()).add(eid)
        return eid

    def _file_evidence(self, result, full=False):
        source, text, version = result['path'], result['content'], result['file_hash']
        self.invalidate(source, version)
        self.raw_texts.add(text)
        if full:
            self.full_reads[source] = version
        if full and self.contract.profile == 'source' and source in SOURCE_UNITS:
            tree = ast.parse(text)
            nodes = [node for node in ast.walk(tree)
                     if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                     and node.name in SOURCE_UNITS[source]]
            if source.endswith('stats_logger.py'):
                nodes += [node for node in tree.body if
                          (isinstance(node, ast.ImportFrom) and node.module == 'deepinfer.logger') or
                          (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'logger'
                                                               for t in node.targets))]
            if not nodes:
                raise ValueError('Required source mechanisms not found: ' + source)
            return [self._add(source, version, f'lines:{n.lineno}-{n.end_lineno}',
                              ast.get_source_segment(text, n), required=True, atomic=True) for n in nodes]
        if 'start_line' in result:
            return [self._add(source, version, f"lines:{result['start_line']}-{result['end_line']}", text,
                              atomic=self.contract.profile == 'source')]
        # Ordinary files may be paged; required source mechanisms above stay whole.
        lines = text.splitlines(keepends=True)
        ids, chunk, start = [], '', 1
        for line_number, line in enumerate(lines, 1):
            if chunk and len(chunk) + len(line) > 4500:
                ids.append(self._add(source, version, f'lines:{start}-{line_number-1}', chunk))
                chunk, start = '', line_number
            chunk += line
        if chunk or not ids:
            ids.append(self._add(source, version, f'lines:{start}-{len(lines)}', chunk))
        if full:
            self.full_read_ids[source] = ids
        return ids

    def observe(self, name, arguments, result):
        ids = []
        if name in {'read_file', 'read_range', 'read_symbol'} and 'content' in result:
            ids = self._file_evidence(result, full=name == 'read_file')
        elif name in {'read_pdf', 'run_command'}:
            data = result
            if name == 'run_command':
                argv = arguments.get('argv', [])
                if len(argv) < 2 or argv[1] not in {'read_pdf.py', 'read_source.py'} or result.get('rc'):
                    data = {}
                else:
                    data = json.loads(result['stdout'])
            if 'pages' in data:
                version = self.workspace.current_hash('paper.pdf')
                self.invalidate('paper.pdf', version)
                ids = [self._add('paper.pdf', version, f"page:{p['page']}", p['text'],
                                 required=p['page'] in self.contract.paper_pages, page=p['page'], atomic=True)
                       for p in data['pages']]
            elif 'ranges' in data:
                source = str(data.get('path', ''))
                try:
                    from pathlib import Path
                    source = Path(source).relative_to(self.workspace.repo).as_posix()
                except ValueError:
                    pass
                for item in data['ranges']:
                    ids.extend(self._file_evidence({**item, 'path': source,
                               'file_hash': self.workspace.current_hash(source)}))
        if ids:
            result['evidence_ids'] = ids
        signature = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
        self.repeats = self.repeats + 1 if signature == self._signature else 0
        self._signature = signature
        summary = {k: v for k, v in result.items() if k not in {'content', 'stdout', 'pages'}}
        if 'stdout' in result and not ids:
            summary['stdout'] = result['stdout'][-2400:]
            if len(result['stdout']) > len(summary['stdout']):
                self.log('context_clip', scope='recent_tool_summary', tool=name,
                         original_chars=len(result['stdout']), sent_chars=len(summary['stdout']),
                         retained=True)
        self.recent_results.append({'tool': name, 'result': summary})
        self.recent_results = self.recent_results[-8:]
        return result

    def invalidate(self, source, current_version):
        invalid = {eid for eid, item in self.items.items()
                   if item.source == source and item.valid and item.version != current_version}
        if not invalid:
            return
        for eid in invalid:
            self.items[eid].valid = False
            self.received_ranges.pop(eid, None)
            self.recall_ranges.pop(eid, None)
        self.exposed -= invalid
        self.current -= invalid
        self.required.get(source, set()).difference_update(invalid)
        if self.full_reads.get(source) != current_version:
            self.full_reads.pop(source, None)
            self.full_read_ids.pop(source, None)
        self.pending = [eid for eid in self.pending if eid not in invalid]
        for note in self.notes.values():
            if invalid.intersection(note['evidence_ids']):
                note['valid'] = False
        self.log('evidence_invalidated', source=source, evidence_ids=sorted(invalid))

    def refresh(self):
        sources = {e.source for e in self.items.values() if e.valid}
        for source in sources:
            self.invalidate(source, self.workspace.current_hash(source))

    @staticmethod
    def merge_ranges(ranges):
        merged = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return merged

    def delivery_range(self, eid):
        """Next contiguous gap, with explicit recalls tracked independently."""
        item = self.items[eid]
        ranges = self.recall_ranges.get(eid, []) if eid in self.pending else self.received_ranges.get(eid, [])
        if eid in self.exposed and eid not in self.pending:
            return 0, len(item.text)  # Optional reuse of a previously exposed item.
        start = 0
        for left, right in self.merge_ranges(ranges):
            if left > start:
                return start, left
            start = max(start, right)
        return start, len(item.text)

    def render(self, eid, start=0, end=None):
        item = self.items[eid]
        end = len(item.text) if end is None else end
        span = '' if start == 0 and end == len(item.text) else f' | characters:{start}:{end}/{len(item.text)}'
        return (f'Evidence {eid} | {item.source} | {item.locator} | sha256={item.version}{span}\n'
                + item.text[start:end])

    def file_exposed(self, source):
        ids = self.full_read_ids.get(source, [])
        return bool(ids) and set(ids).issubset(self.exposed)

    def mark_exposed(self, body, response, number):
        self.refresh()
        self.current = {eid for eid, item in self.items.items() if item.valid and item.text
                        and contains(body, item.text) and (len(item.text) >= 80 or contains(body, item.version))}
        delivered = []
        for eid, start, end in self.offered:
            item = self.items[eid]
            if not item.valid or not contains(body, self.render(eid, start, end)):
                continue
            delivered.append({'id': eid, 'start': start, 'end': end, 'length': len(item.text)})
            self.received_ranges[eid] = self.merge_ranges(self.received_ranges.get(eid, []) + [[start, end]])
            if eid in self.pending:
                self.recall_ranges[eid] = self.merge_ranges(self.recall_ranges.get(eid, []) + [[start, end]])
            if self.received_ranges[eid] == [[0, len(item.text)]]:
                self.exposed.add(eid)
            if start == 0 and end == len(item.text):
                self.current.add(eid)
        self.exposed |= self.current
        for eid in self.current:
            self.received_ranges[eid] = [[0, len(self.items[eid].text)]]
        self.current_notes = {key for key, note in self.notes.items()
                              if note['valid'] and contains(body, note['content'])}
        self.pending = [eid for eid in self.pending if eid not in self.current
                        and self.recall_ranges.get(eid) != [[0, len(self.items[eid].text)]]]
        self.last_response, self.request_number = response, number
        self.log('context_exposure', request=number, evidence_ids=sorted(self.current),
                 note_ids=sorted(self.current_notes), delivered_ranges=delivered,
                 fully_exposed_ids=sorted(self.exposed))
        self.offered = []

    def write_note(self, title, content, evidence_ids, section=None):
        if not isinstance(content, str) or not 20 <= len(content) <= (1500 if section else 3000):
            raise ValueError('Notes require 20..1500 characters for paper, otherwise 20..3000')
        if not evidence_ids or any(eid not in self.exposed or not self.items[eid].valid for eid in evidence_ids):
            raise ValueError('Notes must cite current-version evidence already sent to the model')
        if not contains(self.last_response, content):
            raise ValueError('Note text must occur in the actual last model response; use a literal string')
        sources = sorted({self.items[eid].source for eid in evidence_ids})
        if self.contract.profile == 'source':
            for source in sources:
                if not self.required.get(source, set()).issubset(self.exposed):
                    raise ValueError('Read all required mechanisms for this source before recording its note: ' + source)
            # Bind the note to every mechanism required by its named source.
            evidence_ids = sorted(set(evidence_ids).union(*(self.required.get(s, set()) for s in sources)))
        if self.contract.profile == 'paper' and section not in self.contract.topics:
            raise ValueError('A paper note needs one of the five section ids')
        key = section or title
        if not isinstance(key, str) or not key.strip():
            raise ValueError('A note needs a nonempty title')
        total = len(content) + sum(len(n['content']) for k, n in self.notes.items()
                                   if k != key and n['valid'])
        if total > 9000:
            raise ValueError('Notes exceed 9000 characters; consolidate existing notes before adding more')
        note = {'id': key, 'content': content, 'sources': sources, 'evidence_ids': evidence_ids,
                'valid': True, 'request': self.request_number}
        self.notes[key] = note
        if section:
            pages = sorted({self.items[eid].page for eid in evidence_ids if self.items[eid].page is not None})
            self.log('section_note', section=section, pages=pages, content=content)
        else:
            self.log('context_note', sources=sources, content=content)
        return {'note_id': key, 'sources': sources, 'chars': len(content)}

    def recall(self, evidence_ids, capacity):
        ready, queued, used = [], [], 0
        for eid in dict.fromkeys(evidence_ids):
            if eid not in self.items or not self.items[eid].valid:
                raise ValueError('Evidence is missing or stale: ' + eid)
            cost = len(json.dumps(self.items[eid].text, ensure_ascii=False)) + 200
            (ready if used + cost <= capacity else queued).append(eid)
            if used + cost <= capacity:
                used += cost
            if eid not in self.pending:
                self.pending.append(eid)
                self.recall_ranges[eid] = []
        return {'scheduled': ready, 'pending': queued, 'capacity_chars': capacity,
                'message': 'The selector confirms each actual batch; remaining items stay queued.'}

    def source_reused(self, source):
        needed = self.required.get(source, set())
        if not needed or not needed.issubset(self.exposed):
            return False
        if needed.issubset(self.current):
            return True
        return any(key in self.current_notes and note['valid'] and source in note['sources']
                   and needed.issubset(note['evidence_ids']) for key, note in self.notes.items())

    def source_priorities(self):
        result = []
        for source in sorted(self.contract.required_reads):
            if self.contract.profile == 'source' and not self.source_reused(source):
                result.extend(sorted(self.required.get(source, set()) - self.exposed))
                if self.required.get(source, set()).issubset(self.exposed):
                    result.extend(sorted(self.required.get(source, set())))
        return list(dict.fromkeys(result))

    def missing(self, first_write=True):
        self.refresh()
        issues = []
        if first_write or self.contract.profile == 'paper':
            for source in sorted(self.contract.required_reads):
                if source not in self.full_reads:
                    issues.append('read_file: ' + source)
                elif self.contract.profile in {'basic', 'generic'} and not self.file_exposed(source):
                    issues.append('source read but not yet fully sent: ' + source)
        if self.contract.profile == 'source' and first_write:
            for source in sorted(self.contract.required_reads):
                if not self.source_reused(source):
                    issues.append('read/reuse complete mechanisms or source note: ' + source)
        if self.contract.profile == 'paper':
            pages = {self.items[eid].page for eid in self.exposed if self.items[eid].valid}
            missing = sorted(set(self.contract.paper_pages) - pages)
            if missing:
                issues.append('PDF pages not yet sent: ' + ','.join(map(str, missing)))
            for topic in self.contract.topics:
                if topic not in self.current_notes:
                    issues.append('write/reuse final section note: ' + topic)
        return issues

    def catalog(self):
        return [{k: v for k, v in asdict(item).items() if k != 'text'} | {'chars': len(item.text),
                'exposed': eid in self.exposed} for eid, item in self.items.items() if item.valid]

    def save(self, path):
        path.write_text(json.dumps({'evidence': [asdict(x) for x in self.items.values()],
                                   'notes': self.notes, 'exposed': sorted(self.exposed),
                                   'received_ranges': self.received_ranges,
                                   'full_read_ids': self.full_read_ids},
                                  ensure_ascii=False, indent=2), encoding='utf-8')
