"""CLI wiring; the default rollout remains the previously evaluated legacy engine."""
import json
import os
from pathlib import Path
import sys

from .controller import CodeAgent
from .policies import load_task
from .recording import RunLog


def run_from_args(args):
    entry_dir = Path(__file__).resolve().parent.parent
    config = json.loads((entry_dir / "config.json").read_text(encoding="utf-8"))
    if args.model != config["model"]:
        raise ValueError("--model must match config.json")
    if args.efficiency:
        config["efficiency"] = True
    task_path = Path(args.task).resolve(strict=True)
    task_text = task_path.read_text(encoding="utf-8")
    spec = load_task(task_text, args.repo, config, args.profile, args.allow)
    output = Path.cwd().resolve()
    if output == spec.repo or output.is_relative_to(spec.repo):
        raise ValueError("Run from a separate output directory, outside --repo")
    mode = args.context_mode or os.environ.get("MINI_CONTEXT_MODE") or config.get("context_mode_v2", "evidence")
    action_mode = args.action_mode or config.get("action_mode", "code")
    if action_mode not in {"code", "json"} or mode not in {"baseline", "diagnostic", "evidence"}:
        raise ValueError("Invalid action or context mode")
    log = RunLog(output, config.get("key_env", ""))
    try:
        log("file_read", path=str(task_path), content=task_text)
        agent = CodeAgent(spec, config, output, log, auto=args.auto, action_mode=action_mode,
                          context_mode=mode)
        result = agent.run()
        print(json.dumps({k: result[k] for k in ("status", "reason", "summary", "usage", "evaluation_status")},
                         ensure_ascii=False, indent=2))
        return 0 if result["status"] == "succeeded" else 130 if result["status"] == "interrupted" else 1
    except Exception as exc:
        log("error", error=str(exc))
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        log.close()
