"""CLI and run artifacts; all autonomous decisions execute in official CodeAgent."""
import argparse
import json
import os
from pathlib import Path
import sys

from .audit import AuditedOpenAIModel, BudgetExceeded, RequestAudit
from .context import EvidenceContext
from .engine import make_agent
from .policy import load_task
from .recording import RunLog
from .session import CourseSession


def execute(contract, config, output, auto=True, context_mode='evidence', transport=None, api_key=None):
    log = RunLog(output, config.get('key_env', ''))
    session = CourseSession(contract, output, log, config, auto)
    audit = RequestAudit(contract, log, session.evidence)
    session.audit = audit
    model = AuditedOpenAIModel(config, audit, api_key or os.environ.get(config['key_env'], ''), transport)
    context = EvidenceContext(session) if context_mode == 'evidence' else None
    session.context = context
    agent = make_agent(model, session, context)
    result = {'status': 'failed', 'engine': 'smolagents', 'upstream_version': '1.26.0',
              'context_mode': context_mode, 'reason': None, 'usage': None}
    log('run_start', engine='smolagents', context_mode=context_mode, contract=contract.view(),
        model=config['model'], upstream_commit='12c1bc820eca50ace6f80a21d90426d41d74f845')
    log('file_read', path='task.md', content=contract.text)
    code = 1
    try:
        answer = agent.run(session.task_prompt())
        if not audit.totals()['complete']:
            raise RuntimeError('USAGE_INCOMPLETE')
        result.update(status='completed', answer=str(answer))
        code = 0
    except KeyboardInterrupt:
        result.update(status='interrupted', reason='USER_INTERRUPTED')
        code = 130
    except Exception as exc:
        result['reason'] = audit.stop_reason or (str(exc) if isinstance(exc, BudgetExceeded) else type(exc).__name__ + ': ' + str(exc))
        log('run_error', error=result['reason'])
    finally:
        session.workspace.write_patch()
        session.evidence.save(Path(output) / 'evidence.json')
        (Path(output) / 'memory.json').write_text(json.dumps(
            [step.dict() for step in agent.memory.steps], ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        result.update(usage=audit.totals(), remaining=session.status(compact=True)['remaining'])
        log('run_result', result=result)
        encoded = json.dumps(result, ensure_ascii=False, indent=2)
        if log.secret:
            encoded = encoded.replace(json.dumps(log.secret, ensure_ascii=False)[1:-1], '[REDACTED]')
        (Path(output) / 'run-result.json').write_text(encoded + '\n', encoding='utf-8')
        model.close()
        log.close()
    return code, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--auto', action='store_true')
    parser.add_argument('--context-mode', choices=['evidence', 'upstream'],
                        default=os.environ.get('MINI_CONTEXT_MODE', 'evidence'))
    parser.add_argument('--profile', choices=['auto', 'basic', 'generic', 'source', 'paper'], default='auto')
    parser.add_argument('--allow', nargs='+')
    parser.add_argument('--config', default=str(Path(__file__).resolve().parents[1] / 'config.json'))
    args = parser.parse_args(argv)
    try:
        config = json.loads(Path(args.config).read_text(encoding='utf-8'))
        if args.model != config['model']:
            parser.error('--model must match config.json')
        if args.model != 'deepseek-flash':
            parser.error('This first protocol is fixed to deepseek-flash; compare other modes in a separate protocol')
        if not os.environ.get(config['key_env']):
            parser.error('Configured API key environment variable is missing')
        task = Path(args.task).read_text(encoding='utf-8')
        contract = load_task(task, args.repo, config, args.profile, args.allow)
        code, result = execute(contract, config, Path.cwd(), args.auto, args.context_mode)
        print(json.dumps(result, ensure_ascii=False))
        return code
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
