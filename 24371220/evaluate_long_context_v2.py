"""Run the untouched course evaluators once each; prompt for key only locally."""
import datetime
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parent
    course = root.parents[2] / "materials" / "long-context"
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    env = os.environ.copy()
    env.update(CODE_AGENT_ENGINE="v2", MINI_CONTEXT_MODE="evidence")
    name = config["key_env"]
    # Local-only credentials live outside the submission and Git repository.
    secret_file = root.parents[2] / ".local-secrets" / "code-agent.env"
    if not env.get(name) and secret_file.is_file():
        for line in secret_file.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == name:
                env[name] = value.strip()
                break
    if not env.get(name):
        if not sys.stdin.isatty():
            raise SystemExit("Run interactively to enter the API key without saving it.")
        env[name] = getpass.getpass(f"{name} (hidden, not saved): ").strip()
    if not env.get(name):
        raise SystemExit("No key supplied; no evaluation started.")
    stamp = datetime.datetime.now().strftime("v2-%Y%m%d-%H%M%S")
    out = root / "experiments" / "long-context" / stamp
    out.mkdir(parents=True, exist_ok=False)
    sources = [*root.glob("*.py"), *root.glob("codeagent/**/*.py")]
    protocol = {
        "engine": "v2", "context_mode": "evidence",
        "model": config["model"], "base_url": config["base_url"], "key_env": name,
        "scope": "one source evaluation then one paper evaluation; no automatic retries or efficiency runs",
        "max_model_requests": {"source": 20, "paper": 40},
        "source_sha256": {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "python": sys.version, "results": {},
    }
    def save():
        (out / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
    def run(args):
        return subprocess.run([sys.executable, *map(str, args)], cwd=course, env=env).returncode
    save()
    print(f"Records: {out}", flush=True)
    if run(["prepare.py", "--out", out / "workspace"]):
        raise SystemExit("Source preparation failed; no model run started.")
    source_code = run(["eval_deepinfer.py", "--agent", root / "agent.py", "--repo", out / "workspace/DeepInfer", "--out", out / "source"])
    protocol["results"]["source_exit_code"] = source_code
    save()
    if source_code not in (0, 1):
        print("Source evaluation incomplete; stopping before further paid calls.")
        return source_code
    paper_code = run(["eval_paper.py", "--agent", root / "agent.py", "--out", out / "paper"])
    protocol["results"]["paper_exit_code"] = paper_code
    save()
    print(f"Finished. Records: {out}", flush=True)
    return max(source_code, paper_code)


if __name__ == "__main__":
    raise SystemExit(main())
