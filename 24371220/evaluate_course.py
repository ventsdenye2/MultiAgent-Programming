"""Native WSL course runner. Default: offline preflight. Paid runs require --run-paid."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def run_logged(args, cwd, env, log, timeout=2400):
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen([sys.executable, *map(str, args)], cwd=cwd, env=env,
                                   stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=sys.platform == "linux")
        try:
            return process.wait(timeout=timeout)
        except BaseException:
            if sys.platform == "linux":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if sys.platform == "linux":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
            raise


def preflight(course, out, env):
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("WSL Python 3.12 required")
    for command in ("patch", "pdftotext"):
        if not shutil.which(command):
            raise RuntimeError("Missing executable: " + command)
    if run_logged(["-c", "import pytest"], course, env, out / "dependency-check.log", 30):
        raise RuntimeError("pytest unavailable")
    if run_logged(["prepare.py", "--out", out / "workspace"], course, env, out / "source-preflight.log"):
        raise RuntimeError("Source preparation failed")
    check = "from tools.deepinfer import source_errors; import sys; e,_,_=source_errors(sys.argv[1],False); assert not e,e"
    if run_logged(["-c", check, out / "workspace/DeepInfer"], course, env, out / "source-integrity.log"):
        raise RuntimeError("Source integrity failed")
    rc = run_logged(["-m", "pytest", "-q"], out / "workspace/DeepInfer", env, out / "source-baseline.log", 120)
    if rc not in (0, 1):
        raise RuntimeError("Source pytest could not run")
    metadata_file = next(course.rglob("paper.json"))
    paper = metadata_file.parent
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    samples = []
    for _ in range(3):
        started = time.monotonic()
        result = subprocess.run([sys.executable, str(paper / "read_pdf.py"), "--start-page", "1",
                                 "--end-page", str(metadata["pdf_pages"])], env=env,
                                capture_output=True, timeout=30, check=True)
        pages = json.loads(result.stdout)["pages"]
        digest = hashlib.sha256(json.dumps(pages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        samples.append({"seconds": time.monotonic()-started, "pages": len(pages), "text_sha256": digest})
        save(out / "pdf-preflight.json", samples)
        if samples[-1]["seconds"] >= 30 or len(pages) != metadata["pdf_pages"]:
            raise RuntimeError("PDF extraction failed acceptance")
    if len({x["text_sha256"] for x in samples}) != 1:
        raise RuntimeError("PDF text differs between extractions")
    if run_logged(["-c", "from tools.paper import load_paper_pages; load_paper_pages()"],
                  course, env, out / "paper-integrity.log", 45):
        raise RuntimeError("Course PDF integrity failed")
    return {"source_baseline_exit": rc, "pdf": samples, "status": "passed"}


def infrastructure_failure(stage, rc):
    if rc not in (0, 1):
        return True
    try:
        result = json.loads((stage / "result.json").read_text(encoding="utf-8"))
        agent = json.loads((stage / "development/run-result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return (result.get("status") == "incomplete" or not agent.get("usage", {}).get("complete", False)
            or any(x in str(agent.get("reason", "")) for x in
                   ("MODEL_REQUEST_FAILED", "RUN_TIMEOUT", "USAGE_INCOMPLETE")))


def credentials(root, config, env):
    name = config["key_env"]
    if not env.get(name):
        secret = root.parents[2] / ".local-secrets/code-agent.env"
        if secret.is_file():
            for line in secret.read_text(encoding="utf-8-sig").splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip() == name:
                    env[name] = value.strip()
                    break
    if not env.get(name):
        raise RuntimeError("Configured API key missing; no model request started")


def copy_submission(root, target):
    """Copy and fingerprint all runtime code, including vendor prompts/licenses."""
    target.mkdir()
    for name in ('agent.py', 'legacy_agent.py', 'runtime.py', 'context_selection.py',
                 'config.json', 'requirements.txt', 'requirements.in', 'verify_vendor.py'):
        shutil.copy2(root / name, target / name)
    for name in ('course_agent', 'vendor'):
        shutil.copytree(root / name, target / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    fingerprint = hashes(target)
    for name, digest in fingerprint.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Agent copy verification failed: ' + name)
    return fingerprint


def execute(root, native, archive, preflight_only=True, stage='all'):
    out = native / "results"
    out.mkdir()
    protocol = {"status": "preparing", "native_run": str(native), "archive": str(archive),
                "max_model_requests": {"source": 20, "paper": 40}, "automatic_retries": False,
                "preflight_only": preflight_only, "stage": stage, "results": {}}
    env = os.environ.copy()
    env.update(CODE_AGENT_ENGINE="smolagents", MINI_CONTEXT_MODE="evidence",
               TMPDIR=str(native / "tmp"), PYTHONDONTWRITEBYTECODE="1")
    (native / "tmp").mkdir()
    try:
        save(out / "protocol.json", protocol)
        course = native / "course"
        origin = root.parents[2] / "materials/long-context"
        shutil.copytree(origin, course, ignore=shutil.ignore_patterns(
            ".git", ".venv", "__pycache__", ".pytest_cache", "experiments"))
        protocol["course_sha256"] = hashes(course)
        for name, digest in protocol["course_sha256"].items():
            if hashlib.sha256((origin / name).read_bytes()).hexdigest() != digest:
                raise RuntimeError("Course copy verification failed")
        agent = native / "agent"
        fingerprint = copy_submission(root, agent)
        config = json.loads((agent / "config.json").read_text(encoding="utf-8"))
        protocol.update(agent_sha256=fingerprint, config=config)
        save(out / "protocol.json", protocol)
        for args, filename in [([agent / 'verify_vendor.py'], 'vendor-verification.log'),
                               ([agent / 'agent.py', '--help'], 'submission-startup.log')]:
            if run_logged(args, agent, env, out / filename, 90):
                raise RuntimeError('Copied submission startup failed: ' + filename)
        protocol["preflight"] = preflight(course, out, env)
        protocol["status"] = "preflight_passed"
        save(out / "protocol.json", protocol)
        if preflight_only:
            return 0
        credentials(root, config, env)
        stages = [
            ("source", ["eval_deepinfer.py", "--agent", agent / "agent.py",
                        "--repo", out / "workspace/DeepInfer", "--out", out / "source"]),
            ("paper", ["eval_paper.py", "--agent", agent / "agent.py", "--out", out / "paper"]),
        ]
        if stage in {'smoke', 'basic', 'all'}:
            basic = native / 'basic-course'
            basic.mkdir()
            for name in ('tools', '公开任务'):
                shutil.copytree(root.parent / name, basic / name,
                                ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))
            shutil.copy2(root.parent / 'run_eval.py', basic / 'run_eval.py')
            if stage == 'smoke':
                # One real public coding task is the bounded smoke stage.
                # --case is passed only through the official public checker below.
                prepared = out / 'smoke-attempt'
                rc = run_logged(['tools/check_submission.py', '--case', 'case01_bug_fix', '--prepare', prepared],
                                basic, env, out / 'smoke-prepare.log', 90)
                if rc:
                    raise RuntimeError('Smoke preparation failed')
                rc = run_logged([agent / 'agent.py', '--task', prepared / 'work/task.md',
                                 '--repo', prepared / 'work/repo', '--model', config['model'], '--auto'],
                                prepared / 'run', env, out / 'smoke-agent.log', 600)
                checked = run_logged(['tools/check_submission.py', '--case', 'case01_bug_fix',
                                      '--attempt', prepared, '--agent-exit-code', rc],
                                     basic, env, out / 'smoke-process.log', 120)
                tested = run_logged(['-m', 'pytest', '-q'], prepared / 'work/repo', env,
                                    out / 'smoke-functional.log', 120)
                protocol['results']['smoke'] = {'agent': rc, 'process': checked, 'functional': tested}
                protocol['status'] = 'completed'
                return max(rc, checked, tested)
            rc = run_logged(['run_eval.py', '--agent', agent / 'agent.py', '--out', out / 'basic'],
                            basic, env, out / 'basic-evaluation.log', 3600)
            protocol['results']['basic_exit_code'] = rc
            if rc or stage == 'basic':
                protocol['status'] = 'completed' if rc in (0, 1) else 'infrastructure_failure'
                return rc
        for stage_name, args in stages:
            if stage != 'all' and stage_name != stage:
                continue
            protocol["status"] = stage_name + "_running"
            save(out / "protocol.json", protocol)
            rc = run_logged(args, course, env, out / (stage_name + "-evaluation.log"))
            protocol["results"][stage_name + "_exit_code"] = rc
            if infrastructure_failure(out / stage_name, rc):
                protocol["status"] = "infrastructure_failure"
                return 2
            save(out / "protocol.json", protocol)
            if rc:
                protocol['status'] = 'stage_failed'
                return rc
        protocol["status"] = "completed"
        return max(protocol["results"].values(), default=0)
    except BaseException as exc:
        protocol["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        protocol["error_type"] = type(exc).__name__
        raise
    finally:
        save(out / "protocol.json", protocol)
        try:
            shutil.copytree(out, archive)
            save(archive / "archive-status.json", {"status": "copied", "native_retained": str(native)})
        except Exception as exc:
            save(out / "archive-status.json", {"status": "failed", "error_type": type(exc).__name__})
            print("Archive failed; native results retained at " + str(out), file=sys.stderr)
        print("Native results retained: " + str(out), flush=True)
        print("Archive destination: " + str(archive), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument('--run-paid', action='store_true', help='Explicitly enable real provider requests')
    parser.add_argument('--stage', choices=['smoke', 'basic', 'source', 'paper', 'all'], default='smoke')
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Run using WSL")
    root = Path(__file__).resolve().parent
    native_base = Path.home() / ".local/state/code-agent/evaluations"
    native_base.mkdir(parents=True, exist_ok=True)
    # One paid evaluator per project: concurrent starts can otherwise silently
    # double the user's request spend, even though each individual run is bounded.
    lock = (root / 'experiments/smolagents/.evaluation.lock').open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Another evaluation is active; no new run or model request started')
    native = Path(tempfile.mkdtemp(prefix="run-", dir=native_base))
    fs = subprocess.check_output(["stat", "-f", "-c", "%T", str(native)], text=True).strip()
    if fs not in {"ext2/ext3", "tmpfs", "btrfs", "xfs"}:
        raise RuntimeError("Native Linux filesystem required: " + fs)
    stamp = datetime.datetime.now().strftime("smolagents-%Y%m%d-%H%M%S-%f")
    print("Native run: " + str(native), flush=True)
    return execute(root, native, root / "experiments/smolagents" / stamp,
                   args.preflight_only or not args.run_paid, args.stage)


if __name__ == "__main__":
    raise SystemExit(main())
