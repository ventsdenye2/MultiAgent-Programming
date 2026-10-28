"""Replay this smoke attempt with recorded responses and no provider access.

This diagnostic reruns the saved actions in a fresh copy of the task. HTTP is
replaced by MockTransport; usage is zeroed so replay counts are never billed
usage. Keep its output separate from the paid evaluation archive.
"""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

import course_agent
import httpx
from course_agent.audit import strings
from course_agent.cli import execute
from course_agent.context import EvidenceContext
from course_agent.policy import load_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    events = [json.loads(line) for line in
              (archive / 'smoke-attempt/run/run.log').read_text(encoding='utf-8').splitlines()]
    replies = [e['response'] for e in events if e['event'] == 'model_response']
    protocol = json.loads((archive / 'protocol.json').read_text(encoding='utf-8'))
    cfg = dict(protocol['config'], base_url='https://offline.invalid/v1', key_env='OFFLINE_REPLAY_KEY')
    native = Path(tempfile.mkdtemp(prefix='smoke-context-replay-'))
    shutil.copytree(archive / 'smoke-attempt/before', native / 'work')
    contract = load_task((native / 'work/task.md').read_text(encoding='utf-8'),
                         native / 'work/repo', cfg)
    calls, attempts = [], []
    current = None
    original_build, original_fits = EvidenceContext.build, EvidenceContext.fits

    def capture_fits(context, messages, model):
        accepted = original_fits(context, messages, model)
        current['fit_attempts'].append({
            'body_chars': model.estimate(messages),
            'content_chars': sum(len(s) for m in messages for s in strings(m.content)),
            'message_chars': [sum(len(s) for s in strings(m.content)) for m in messages],
            'accepted': accepted,
        })
        return accepted

    def capture_build(context, memory, model):
        nonlocal current
        current = {'request_number': len(calls) + 1, 'fit_attempts': []}
        attempts.append(current)
        try:
            result = original_build(context, memory, model)
            current['selection'] = context.last_manifest
            return result
        except ValueError as exc:
            current['error'] = str(exc)
            current['stalled_requests'] = context.stalled_requests
            current['recent_results_chars'] = len(json.dumps(context.store.recent_results[-4:],
                                                             ensure_ascii=False))
            raise

    def handler(request):
        index = len(calls)
        calls.append(json.loads(request.content))
        if index >= len(replies):
            raise RuntimeError('RECORDED_RESPONSES_EXHAUSTED: no network fallback')
        payload = json.loads(json.dumps(replies[index]))
        payload['usage'] = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
        return httpx.Response(200, json=payload)

    EvidenceContext.build, EvidenceContext.fits = capture_build, capture_fits
    try:
        rc, result = execute(contract, cfg, native / 'run', transport=httpx.MockTransport(handler),
                             api_key='offline-replay-placeholder')
    finally:
        EvidenceContext.build, EvidenceContext.fits = original_build, original_fits
    shutil.copytree(native / 'run', output / 'run')
    shutil.copytree(native / 'work', output / 'work')
    summary = {
        'kind': 'offline_recorded_response_replay', 'provider_requests': 0,
        'source_archive': str(archive), 'native_retained': str(native),
        'mock_responses_consumed': len(calls), 'agent_exit_code': rc,
        'result': result, 'context_attempts': attempts,
    }
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                                       encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'context_attempts'}, ensure_ascii=False))
    print(json.dumps(attempts[-1], ensure_ascii=False))


if __name__ == '__main__':
    main()
