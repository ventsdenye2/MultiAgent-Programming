"""Offline replay of recorded actions; synthetic usage is NOT a paid evaluation."""
import argparse
import json
from pathlib import Path
import shutil

from codeagent.controller import CodeAgent
from codeagent.policies import load_task
from codeagent.recording import RunLog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    repo = args.out / 'repo'
    shutil.copytree(args.repo, repo)
    replies = [json.loads(p.read_text(encoding='utf-8'))['choices'][0]['message']['content']
               for p in sorted(args.recording.glob('request-*.response'))]
    if not replies:
        raise ValueError('No recorded responses')
    config = json.loads(Path(__file__).with_name('config.json').read_text(encoding='utf-8'))
    config['model'] = 'offline-replay'
    spec = load_task(args.task.read_text(encoding='utf-8'), repo, config, 'source')
    spec.max_calls = len(replies)
    bodies = []
    def transport(body):
        index = len(bodies)
        bodies.append(body)
        return {'model':'offline-replay', 'choices':[{'message':{'content':replies[index]}}],
                'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
    output = args.out / 'execution'
    log = RunLog(output)
    try:
        log('offline_replay', source=str(args.recording), synthetic_usage=True,
            warning='Recorded actions only; no model inference or course score')
        agent = CodeAgent(spec, config, output, log, auto=True, transport=transport)
        result = agent.run()
    finally:
        log.close()
    events = [json.loads(line) for line in (output/'run.log').read_text(encoding='utf-8').splitlines()]
    summary = {'mode':'offline_replay', 'paid_requests':0, 'synthetic_usage':True,
               'actions':len(replies), 'executions':[{'step':e.get('step_id'),'error':e.get('error')}
                 for e in events if e['event']=='code_execution'],
               'state':result['state'], 'stop_reason':result['reason'],
               'errors':[e for e in events if e['event'] in ('tool_error','action_error')]}
    (args.out/'replay-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return int(bool(summary['errors']) or any(e['error'] for e in summary['executions']))


if __name__ == '__main__':
    raise SystemExit(main())
