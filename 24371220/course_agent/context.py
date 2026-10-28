"""EA-CM builds a bounded sending view without deleting upstream memory."""
import json

from smolagents.memory import ActionStep, TaskStep
from smolagents.models import ChatMessage, MessageRole

from .audit import strings


def message(text, role=MessageRole.USER):
    return ChatMessage(role=role, content=[{'type': 'text', 'text': text}])


def clip(text, limit):
    if len(text) <= limit:
        return text
    marker = '\n[full record remains in run.log]\n'
    room = max(0, limit - len(marker))
    left = (room + 1) // 2
    right = room - left
    return text[:left] + marker[:limit] + (text[-right:] if right else '')


class EvidenceContext:
    def __init__(self, session):
        self.session = session
        self.store = session.evidence
        self.log = session.log
        self.last_manifest = {}
        self.capacity = 0
        self.progress_signature = None
        self.stalled_requests = 0

    def fits(self, messages, model):
        spec = self.session.contract
        size = model.measure(messages)
        return (size['chars'] <= min(spec.soft_chars, spec.hard_chars - 128)
                and (not spec.content_chars or size['course_content_chars'] <= spec.content_chars - 128))

    def _recent(self, memory, limits=(1800, 2200, 4000)):
        actions = [step for step in memory.steps if isinstance(step, ActionStep)]
        if not actions:
            return []
        step = actions[-1]
        text = step.observations or ''
        # Large original text has one canonical copy below, never a second copy
        # embedded in the recent executor printout.
        for original in sorted(self.store.raw_texts, key=len, reverse=True):
            if len(original) < 80:
                continue
            for form in (original, json.dumps(original, ensure_ascii=False)[1:-1],
                         json.dumps(original)[1:-1]):
                text = text.replace(form, '[versioned evidence retained separately]')
        feedback = 'Executor output:\n' + clip(text, limits[1] // 2)
        if self.store.recent_results:
            feedback += '\nRecent project tool results:\n' + clip(
                json.dumps(self.store.recent_results[-4:], ensure_ascii=False), limits[1] // 2)
        result = [message('Latest action:\n' + clip(step.code_action or step.model_output or '', limits[0]),
                          MessageRole.ASSISTANT),
                  message('Latest execution feedback:\n' + feedback)]
        error_step = next((s for s in reversed(actions) if s.error), None)
        if error_step:
            # Errors are reserved before document selection. Never drop the
            # entire failing step to make room for another source excerpt.
            result.append(message('Most recent error (check whether subsequent work resolved it):\n' +
                                  clip(str(error_step.error), limits[2])))
        return result

    def _status(self, limit):
        """A sending projection, never a second copy of tool results."""
        status = self.session.status(compact=True)
        unseen = [eid for eid, item in self.store.items.items() if item.valid and eid not in self.store.exposed]
        data = {'next_requirement': status['remaining'][0] if status['remaining'] else 'final_answer when ready',
                'remaining_count': len(status['remaining']), 'requests_left': status['requests_left'],
                'unseen_evidence_count': len(unseen), 'queued_recall_count': len(self.store.pending),
                'plan': [[clip(i['title'], 60), i['status']] for i in status['plan']]}
        if unseen or self.store.pending:
            data['delivery'] = 'Pending originals are sent automatically below; do not reread unchanged files.'
        if self.stalled_requests >= 2:
            data['no_progress_requests'] = self.stalled_requests
            data['recent_tools'] = [x['tool'] for x in self.store.recent_results[-3:]]
        if 'last_response_classification' in status:
            data['last_response_classification'] = status['last_response_classification']
        if status['requests_left'] <= 6:
            data['delivery_reserve'] = 'Complete notes/changes, verify, then final_answer.'
        # Keep actionable blockers and response diagnostics at the front even
        # when plan titles or user-controlled paths are very large.
        if 'last_response_classification' in data:
            data = {'last_response_classification': data.pop('last_response_classification'), **data}
        return message('Course progress (new evidence below can satisfy pending items):\n' +
                       clip(json.dumps(data, ensure_ascii=False), limit))

    def _part(self, eid, messages, model):
        """Fit an ordinary-file range; PDF pages and source mechanisms stay whole."""
        item = self.store.items[eid]
        start, end = self.store.delivery_range(eid)
        if self.fits(messages + [message(self.store.render(eid, start, end))], model):
            return start, end
        if item.atomic or end - start < 128:
            return None
        low, high, best = start + 128, end - 1, None
        while low <= high:
            middle = (low + high) // 2
            if self.fits(messages + [message(self.store.render(eid, start, middle))], model):
                best, low = middle, middle + 1
            else:
                high = middle - 1
        if best is None:
            return None
        boundary = item.text.rfind('\n', start, best) + 1
        return start, boundary if boundary >= start + 128 else best

    def build(self, memory, model):
        self.store.refresh()
        self.store.offered = []
        fixed = memory.system_prompt.to_messages()
        for step in memory.steps:
            if isinstance(step, TaskStep):
                fixed.extend(step.to_messages())
        progress = repr((self.store.full_reads, sorted(self.store.exposed), self.store.received_ranges,
                         self.store.notes, sorted(self.session.writes), self.session.verified, self.session.plan))
        self.stalled_requests = self.stalled_requests + 1 if progress == self.progress_signature else 0
        self.progress_signature = progress
        prefix = recent = None
        minimum = None
        for status_limit, limits in ((500, (120, 240, 500)), (300, (80, 160, 256))):
            trial_prefix, trial_recent = fixed + [self._status(status_limit)], self._recent(memory, limits)
            if self.fits(trial_prefix + trial_recent, model):
                prefix, recent, minimum = trial_prefix, trial_recent, limits
                break
        if prefix is None:
            size = model.measure(trial_prefix + trial_recent)
            self.log('context_blocked', reason='fixed', **size)
            raise ValueError('CONTEXT_FIXED_OVERFLOW: minimum sending view exceeds budget: ' + json.dumps(size))
        base = prefix + recent
        payload, selected_notes, optional_notes = [], [], []
        read_pages = {self.store.items[eid].page for eid in self.store.exposed if self.store.items[eid].valid}
        paper_reading = (self.session.contract.profile == 'paper' and
                         not set(self.session.contract.paper_pages).issubset(read_pages))
        for key, note in self.store.notes.items():
            if not note['valid']:
                continue
            candidate = message(f"Model-authored note {key}, sources={note['sources']}:\n{note['content']}")
            required = self.session.contract.profile == 'source' or (
                self.session.contract.profile == 'paper' and not paper_reading)
            if required and self.fits(base + payload + [candidate], model):
                payload.append(candidate)
                selected_notes.append(key)
            else:
                optional_notes.append((key, candidate))
        available = model.measure(base + payload)
        rooms = [self.session.contract.soft_chars - available['chars']]
        if self.session.contract.content_chars:
            rooms.append(self.session.contract.content_chars - available['course_content_chars'])
        self.capacity = max(0, min(rooms) - 400)
        valid = [eid for eid, item in self.store.items.items() if item.valid]
        unseen = [eid for eid in valid if eid not in self.store.exposed]
        required_unseen = [eid for eid in unseen if self.store.items[eid].required or
                           self.store.items[eid].source in self.session.contract.required_reads]
        reuse = valid[-6:] if self.session.contract.profile != 'paper' else []
        priorities = list(dict.fromkeys(self.store.pending + required_unseen + unseen +
                                       self.store.source_priorities() + reuse))
        selected, deferred, offered = [], [], []
        for eid in priorities:
            item = self.store.items[eid]
            if not item.valid:
                continue
            represented = any(item.source in self.store.notes[k]['sources'] and
                              eid in self.store.notes[k]['evidence_ids'] for k in selected_notes)
            if represented and eid not in unseen and eid not in self.store.pending:
                continue
            part = self._part(eid, base + payload, model)
            if part is None:
                deferred.append(eid)
                continue
            start, end = part
            payload.append(message(self.store.render(eid, start, end)))
            selected.append(eid)
            offered.append((eid, start, end))
            if start or end != len(item.text):
                deferred.append(eid)
        for key, candidate in optional_notes:
            if self.fits(base + payload + [candidate], model):
                payload.append(candidate)
                selected_notes.append(key)
        # Expansion happens only after sources needed for progress are reserved.
        for limits in ((1800, 2200, 4000), (800, 900, 2000), (250, 500, 1200), minimum):
            candidate = self._recent(memory, limits)
            if self.fits(prefix + candidate + payload, model):
                recent = candidate
                break
        messages = prefix + recent + payload
        if deferred:
            notice = message('Not fully delivered yet: ' + ', '.join(deferred[:8]) +
                             '. Continue the pending batch; do not reread unchanged sources. '
                             'Write notes only from originals already received.')
            if self.fits(messages + [notice], model):
                messages.append(notice)
            self.log('context_drop', scope='sending_view', retained=True, evidence_ids=deferred)
        if len([s for s in memory.steps if isinstance(s, ActionStep)]) > 0:
            original = next(s for s in reversed(memory.steps) if isinstance(s, ActionStep))
            sent = sum(len(s) for m in recent for s in strings(m.content))
            if len(original.observations or '') > sent:
                self.log('context_clip', scope='sending_view', original_chars=len(original.observations or ''),
                         sent_chars=sent, retained=True)
        self.store.offered = offered
        size = model.measure(messages)
        self.last_manifest = {'evidence_ids': selected, 'note_ids': selected_notes, 'deferred': deferred,
                              'delivered_parts': offered, 'estimated_body_chars': size['chars'],
                              'course_content_chars': size['course_content_chars'],
                              'budget_parts': {'fixed': model.measure(fixed)['chars'],
                                               'minimum_frame': model.measure(base)['chars'],
                                               'payload_text': sum(len(s) for m in payload for s in strings(m.content))},
                              'reason': 'reserve required evidence before expanding recent feedback'}
        self.log('context_selection', **self.last_manifest)
        return messages
