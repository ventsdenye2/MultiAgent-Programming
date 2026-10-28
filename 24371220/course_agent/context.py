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
    return text[:limit // 2] + '\n[full record remains in run.log]\n' + text[-limit // 2:]


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
        content = sum(len(s) for m in messages for s in strings(m.content))
        return (model.estimate(messages) <= min(spec.soft_chars, spec.hard_chars - 128)
                and (not spec.content_chars or content <= spec.content_chars - 128))

    def _recent(self, memory):
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
        result = [message('Latest action:\n' + clip(step.code_action or step.model_output or '', 1800),
                          MessageRole.ASSISTANT),
                  message('Latest execution feedback:\n' + clip(text, 2200))]
        if step.error:
            # Errors are reserved before document selection. Never drop the
            # entire failing step to make room for another source excerpt.
            result.append(message('Unresolved error from latest action:\n' + clip(str(step.error), 4000)))
        return result

    def build(self, memory, model):
        self.store.refresh()
        messages = memory.system_prompt.to_messages()
        for step in memory.steps:
            if isinstance(step, TaskStep):
                messages.extend(step.to_messages())
        status = self.session.status(compact=True)
        progress = repr((self.store.full_reads, sorted(self.store.exposed), self.store.notes,
                         sorted(self.session.writes), self.session.verified, self.session.plan))
        self.stalled_requests = self.stalled_requests + 1 if progress == self.progress_signature else 0
        self.progress_signature = progress
        if self.stalled_requests >= 2:
            status['no_progress_requests'] = self.stalled_requests
            status['recent_actions'] = self.store.recent_results[-4:]
            status['recovery'] = 'Use the explicit remaining requirements; replace repeated reads with notes or pending evidence.'
        if status['requests_left'] <= 6:
            status['delivery_reserve'] = 'Reserve remaining requests for required notes, changes, verification and final_answer.'
        messages.append(message('Course progress before this request (new evidence below can satisfy missing items):\n'
                                + json.dumps(status, ensure_ascii=False)))
        messages += self._recent(memory)
        if not self.fits(messages, model):
            raise ValueError('CONTEXT_FIXED_OVERFLOW: task, tools and recent feedback exceed budget')
        selected_notes = []
        read_pages = {self.store.items[eid].page for eid in self.store.exposed if self.store.items[eid].valid}
        paper_reading = (self.session.contract.profile == 'paper' and
                         not set(self.session.contract.paper_pages).issubset(read_pages))
        optional_notes = []
        for key, note in self.store.notes.items():
            if not note['valid']:
                continue
            candidate = message(f"Model-authored note {key}, sources={note['sources']}:\n{note['content']}")
            if paper_reading:
                optional_notes.append((key, candidate))
                continue
            if not self.fits(messages + [candidate], model):
                raise ValueError('CONTEXT_NOTE_OVERFLOW: shorten notes using their cited evidence')
            messages.append(candidate)
            selected_notes.append(key)
        self.capacity = max(0, self.session.contract.soft_chars - model.estimate(messages) - 500)
        valid = [eid for eid, item in self.store.items.items() if item.valid]
        unseen = [eid for eid in valid if eid not in self.store.exposed]
        priorities = list(dict.fromkeys(self.store.pending + unseen + self.store.source_priorities() + valid[-6:]))
        selected, deferred = [], []
        for eid in priorities:
            item = self.store.items[eid]
            if not item.valid:
                continue
            # A source note already contains the required retained meaning.
            represented = any(item.source in self.store.notes[k]['sources'] and
                              eid in self.store.notes[k]['evidence_ids'] for k in selected_notes)
            if represented and eid not in unseen and eid not in self.store.pending:
                continue
            candidate = message(f'Evidence {eid} | {item.source} | {item.locator} | sha256={item.version}\n{item.text}')
            if self.fits(messages + [candidate], model):
                messages.append(candidate)
                selected.append(eid)
            else:
                deferred.append(eid)
        for key, candidate in optional_notes:
            if self.fits(messages + [candidate], model):
                messages.append(candidate)
                selected_notes.append(key)
        if deferred:
            notice = message('Deferred evidence (capacity, automatically retained for later): ' + ', '.join(deferred[:30]) +
                             '\nUse write_note with a literal summary of the received sources/pages to preserve meaning. '
                             'Do not reread unchanged full files. Continue pending reads only after writing useful notes. '
                             'When reading is complete, merge the five section notes, write the report, then verify.')
            if self.fits(messages + [notice], model):
                messages.append(notice)
        self.last_manifest = {'evidence_ids': selected, 'note_ids': selected_notes, 'deferred': deferred,
                              'estimated_body_chars': model.estimate(messages),
                              'reason': 'reserve latest feedback; retain notes; recall; unseen evidence; edit prerequisites'}
        self.log('context_selection', **self.last_manifest)
        return messages
