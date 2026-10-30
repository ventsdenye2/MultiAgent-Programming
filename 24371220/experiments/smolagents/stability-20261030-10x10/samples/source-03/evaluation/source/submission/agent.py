"""Course entry point: official smolagents kernel, with optional EA-CM context."""
import os
import sys


def __getattr__(name):
    # Historical tests import Agent/SYSTEM; the default CLI never runs that loop.
    if name in {'Agent', 'SYSTEM'}:
        import legacy_agent
        return getattr(legacy_agent, name)
    raise AttributeError(name)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    engine = os.environ.get('CODE_AGENT_ENGINE', 'smolagents')
    for i, arg in enumerate(args):
        if arg.startswith('--engine='):
            engine = arg.split('=', 1)[1]
            args.pop(i)
            break
        if arg == '--engine':
            if i + 1 >= len(args):
                raise SystemExit('--engine requires smolagents or legacy')
            engine = args[i + 1]
            del args[i:i + 2]
            break
    if engine == 'legacy':
        import legacy_agent
        sys.argv = [sys.argv[0], *args]
        return legacy_agent.main()
    if engine != 'smolagents':
        raise SystemExit('Unknown engine: ' + engine)
    from course_agent.cli import main as run
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
