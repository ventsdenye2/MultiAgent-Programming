"""Preflight-gated native Linux course evaluation; no automatic paid retries."""
import argparse
import datetime
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


def execute(root, native, archive, preflight_only=False):
    out = native / "results"
    out.mkdir()
    protocol = {"status": "preparing", "native_run": str(native), "archive": str(archive),
                "max_model_requests": {"source": 20, "paper": 40}, "automatic_retries": False,
                "preflight_only": preflight_only, "results": {}}
    env = os.environ.copy()
    env.update(CODE_AGENT_ENGINE="v2", MINI_CONTEXT_MODE="evidence",
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
        agent.mkdir()
        for path in [*root.glob("*.py"), root / "config.json"]:
            shutil.copy2(path, agent / path.name)
        shutil.copytree(root / "codeagent", agent / "codeagent", ignore=shutil.ignore_patterns("__pycache__"))
        config = json.loads((agent / "config.json").read_text(encoding="utf-8"))
        protocol.update(agent_sha256=hashes(agent), config=config)
        save(out / "protocol.json", protocol)
        protocol["preflight"] = preflight(course, out, env)
        protocol["status"] = "preflight_passed"
        save(out / "protocol.json", protocol)
        if preflight_only:
            return 0
        credentials(root, config, env)
        for stage, args in [
            ("source", ["eval_deepinfer.py", "--agent", agent / "agent.py",
                        "--repo", out / "workspace/DeepInfer", "--out", out / "source"]),
            ("paper", ["eval_paper.py", "--agent", agent / "agent.py", "--out", out / "paper"]),
        ]:
            protocol["status"] = stage + "_running"
            save(out / "protocol.json", protocol)
            rc = run_logged(args, course, env, out / (stage + "-evaluation.log"))
            protocol["results"][stage + "_exit_code"] = rc
            if infrastructure_failure(out / stage, rc):
                protocol["status"] = "infrastructure_failure"
                return 2
            save(out / "protocol.json", protocol)
        protocol["status"] = "completed"
        return max(protocol["results"].values())
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
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Run using WSL")
    root = Path(__file__).resolve().parent
    native_base = Path.home() / ".local/state/code-agent/evaluations"
    native_base.mkdir(parents=True, exist_ok=True)
    native = Path(tempfile.mkdtemp(prefix="run-", dir=native_base))
    fs = subprocess.check_output(["stat", "-f", "-c", "%T", str(native)], text=True).strip()
    if fs not in {"ext2/ext3", "tmpfs", "btrfs", "xfs"}:
        raise RuntimeError("Native Linux filesystem required: " + fs)
    stamp = datetime.datetime.now().strftime("v2-%Y%m%d-%H%M%S-%f")
    print("Native run: " + str(native), flush=True)
    return execute(root, native, root / "experiments/long-context" / stamp, args.preflight_only)


if __name__ == "__main__":
    raise SystemExit(main())
