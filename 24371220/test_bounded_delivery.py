"""Offline wire-level checks of evidence confirmation and page recalls."""
from types import SimpleNamespace

import httpx
import pytest

from course_agent.audit import RequestAudit
from course_agent.evidence import EvidenceStore


class Workspace:
    version = 'v1'

    def current_hash(self, source):
        return self.version


@pytest.fixture
def state():
    workspace = Workspace()
    contract = SimpleNamespace(profile='paper', paper_pages=[1, 2], max_calls=50,
                               timeout=1000, hard_chars=32000, content_chars=None)
    store = EvidenceStore(contract, workspace, lambda *args, **kwargs: None)
    store.observe('read_pdf', {}, {'pages': [
        {'page': 1, 'text': 'First page original. ' * 10},
        {'page': 2, 'text': 'Second page original. ' * 10},
        {'page': 99, 'text': 'Appendix page original. ' * 10},
    ]})
    audit = RequestAudit(contract, lambda *args, **kwargs: None, store)
    return store, workspace, audit


def send(audit, store, ids, content='ok', fail=False):
    store.offered = [(eid, 0, len(store.items[eid].text)) for eid in ids]
    body = {'messages': [{'role': 'user', 'content': '\n'.join(store.render(eid) for eid in ids)}]}

    def respond(request):
        if fail:
            raise httpx.ConnectError('offline simulated failure', request=request)
        return httpx.Response(200, json={'choices': [{'message': {'content': content},
                                                      'finish_reason': 'stop'}]})

    with httpx.Client(transport=httpx.MockTransport(respond),
                      event_hooks={'request': [audit.request], 'response': [audit.response]}) as client:
        return client.post('https://offline.invalid/', json=body)


def test_actual_confirmation_has_one_nonrenewable_window(state):
    store, _, audit = state
    first = store.pending[0]
    send(audit, store, [first])
    assert store.confirmed_anchor[first] == 1
    assert first not in store.pending
    assert store.eligible_auto(first, 2)
    send(audit, store, [first])  # automatic carry cannot renew the anchor
    assert store.confirmed_anchor[first] == 1
    assert not store.eligible_auto(first, 3)
    store.recall([first])
    send(audit, store, [first])
    assert store.confirmed_anchor[first] == 3
    assert store.eligible_auto(first, 4)
    assert not store.eligible_auto(first, 5)


def test_empty_and_failed_requests_preserve_pending(state):
    store, _, audit = state
    first = store.pending[0]
    send(audit, store, [first], content='')
    assert first in store.pending and first not in store.confirmed_anchor
    with pytest.raises(httpx.ConnectError):
        send(audit, store, [first], fail=True)
    assert first in store.pending and first not in store.confirmed_anchor
    send(audit, store, [first])
    assert store.confirmed_anchor[first] == 3
    store.recall([first])
    store.recall([first])
    send(audit, store, [first], content='')
    assert store.pending.count(first) == 1 and store.confirmed_anchor[first] == 3
    send(audit, store, [first])
    assert first not in store.pending and store.confirmed_anchor[first] == 5


def test_recall_pages_validates_whole_batch_and_allows_appendix(state):
    store, _, _ = state
    store.pending.clear()
    ids = list(store.items)
    result = store.recall_pages([99, 1, 99])
    assert store.pending == [ids[2], ids[0]]
    assert result['requested_count'] == 2
    for invalid in ([2, True], [2, '1'], [2, 100], [], '1'):
        before = list(store.pending)
        with pytest.raises(ValueError):
            store.recall_pages(invalid)
        assert store.pending == before


def test_version_change_removes_old_anchors_and_demands(state):
    store, workspace, audit = state
    first = store.pending[0]
    send(audit, store, [first])
    store.recall([first])
    workspace.version = 'v2'
    with pytest.raises(ValueError):
        store.recall_pages([1])
    store.refresh()
    assert first not in store.pending and first not in store.confirmed_anchor
    assert not store.eligible_auto(first, 2)
