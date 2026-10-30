"""Course file/command operations; exposed through upstream smolagents.Tool."""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


TOOL_SPECS = {
    "list_files": {"description": "List text files under a repository path.", "parameters": _schema({"path": {"type": "string"}, "limit": {"type": "integer"}, "offset": {"type": "integer"}}, [])},
    "search_code": {"description": "Search visible text source files for a literal string.", "parameters": _schema({"query": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}}, ["query"])},
    "read_file": {"description": "Read a text file in full.", "parameters": _schema({"path": {"type": "string"}}, ["path"])},
    "read_range": {"description": "Read an inclusive line range from a text file.", "parameters": _schema({"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, ["path", "start_line", "end_line"])},
    "read_symbol": {"description": "Read a complete Python class or function including decorators.", "parameters": _schema({"path": {"type": "string"}, "symbol": {"type": "string"}}, ["path", "symbol"])},
    "write_file": {"description": "Replace an editable text file after checking its current hash.", "parameters": _schema({"path": {"type": "string"}, "content": {"type": "string"}, "expected_hash": {"type": "string"}}, ["path", "content", "expected_hash"])},
    "replace_text": {"description": "Replace one unique text occurrence after checking its current hash.", "parameters": _schema({"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}, "expected_hash": {"type": "string"}}, ["path", "old_text", "new_text", "expected_hash"])},
    "read_pdf": {"description": "Read pages using the repository's read_pdf.py helper.", "parameters": _schema({"start_page": {"type": "integer"}, "end_page": {"type": "integer"}}, ["start_page"])},
    "run_command": {"description": "Run one allowed argv command without a shell. Omit cwd or use '.' for the task repository root.", "parameters": _schema({"argv": {"type": "array", "items": {"type": "string"}}, "cwd": {"type": "string"}}, ["argv"])},
}

_SECRET_NAMES = {".env", "credentials", "credentials.json", "secrets.json", "id_rsa", "id_ed25519", "known_hosts", "auth.json"}
_SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", ".pytest_cache"}
_MAX_FILE_BYTES = 1_000_000
_MAX_SCAN_FILES = 20_000
_HASH_CHUNK_BYTES = 1024 * 1024


class WorkspaceTools:
    def __init__(self, repo, output, editable, log, command_rules=None, command_timeout=120, key_env=""):
        self.repo = Path(repo).resolve()
        self.output = Path(output).resolve()
        self.editable = {self._norm_rel(p) for p in editable}
        self.log = log
        self.command_rules = [list(x) for x in (command_rules or [])]
        self.command_timeout = command_timeout
        self.key_env = key_env
        if not isinstance(command_timeout, (int, float)) or command_timeout <= 0:
            raise ValueError("command_timeout must be positive")
        self._snapshot: dict[str, str] = {}
        for rel in self.editable:
            try:
                content = self._read_bytes(self._resolve(rel)).decode("utf-8")
            except FileNotFoundError:
                content = None
            self._snapshot[rel] = content
            self.log("snapshot", path=rel, content=content)

    def _norm_rel(self, value: str) -> str:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError("invalid path")
        p = Path(value)
        if p.is_absolute():
            try:
                p = p.relative_to(self.repo)
            except ValueError:
                raise ValueError("path must remain inside the task repository; use '.' for its root") from None
        if any(part in ("..", "") for part in p.parts):
            raise ValueError("path must remain inside the task repository")
        rel = p.as_posix()
        if rel == ".": return "."
        if any(part.lower() == ".git" for part in p.parts) or self._is_secret(p):
            raise ValueError("path is restricted")
        return rel

    @staticmethod
    def _is_secret(p: Path) -> bool:
        for part in p.parts:
            name = part.lower()
            if name.startswith(".") or name in _SECRET_NAMES or name.startswith(".env"):
                return True
        return False

    def _resolve(self, value: str, *, allow_dir=False) -> Path:
        rel = self._norm_rel(value)
        path = (self.repo / rel).resolve()
        if path != self.repo and self.repo not in path.parents:
            raise ValueError("path escapes repository")
        if any(part.lower() == ".git" for part in path.relative_to(self.repo).parts) if path != self.repo else False:
            raise ValueError(".git is restricted")
        if self._is_secret(path.relative_to(self.repo)) if path != self.repo else False:
            raise ValueError("sensitive file is restricted")
        if not allow_dir:
            try: mode = path.stat().st_mode
            except FileNotFoundError: raise FileNotFoundError("file does not exist")
            if not stat.S_ISREG(mode): raise OSError("path is not a regular file")
        return path

    @staticmethod
    def _read_bytes(path: Path) -> bytes:
        data = path.read_bytes()
        if b"\x00" in data: raise ValueError("binary files are not supported")
        return data

    def current_hash(self, path):
        digest = hashlib.sha256()
        try:
            resolved = self._resolve(str(path))
            with resolved.open("rb") as stream:
                while True:
                    block = stream.read(_HASH_CHUNK_BYTES)
                    if not block: break
                    digest.update(block)
        except FileNotFoundError:
            return "missing"
        return digest.hexdigest()

    def _read(self, rel):
        path = self._resolve(rel)
        data = self._read_bytes(path)
        try: content = data.decode("utf-8")
        except UnicodeError as exc: raise ValueError("file is not UTF-8 text") from exc
        return path, content, hashlib.sha256(data).hexdigest()

    def _result_read(self, rel, content, digest, **extra):
        self.log("file_read", path=rel, content=content, **extra)
        return {"path": rel, "content": content, "file_hash": digest, **extra}

    def _check_editable(self, rel):
        rel = self._norm_rel(rel)
        if rel not in self.editable: raise ValueError("file is not editable")
        return rel

    def _atomic_write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".agent-write-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(content); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def _write(self, rel, content, expected_hash):
        rel = self._check_editable(rel)
        if not isinstance(content, str): raise ValueError("content must be text")
        path = self._resolve(rel, allow_dir=True)
        if path.exists(): _, old, before = self._read(rel)
        else: old, before = "", "missing"
        if before != expected_hash: raise ValueError("file hash changed; reread before writing")
        changed = before == "missing" or old != content
        if changed: self._atomic_write(path, content)
        after = self.current_hash(rel)
        self.log("file_write", path=rel, content=content, before_hash=before, file_hash=after, changed=changed)
        return {"path": rel, "file_hash": after, "before_hash": before, "changed": changed}

    def _files(self, start: str):
        base = self._resolve(start, allow_dir=True)
        if not base.is_dir(): raise ValueError("path is not a directory")
        result = []
        scanned = 0
        for root, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d.lower() not in _SKIP_DIRS and not d.startswith(".") and not self._is_secret(Path(d)) and not (Path(root) / d).is_symlink())
            for f in sorted(files):
                p = Path(root) / f
                rel = p.relative_to(self.repo).as_posix()
                if f.startswith(".") or self._is_secret(Path(f)) or p.is_symlink(): continue
                scanned += 1
                if scanned > _MAX_SCAN_FILES: return sorted(result)
                try:
                    if p.stat().st_size > _MAX_FILE_BYTES: continue
                    data = p.read_bytes()
                    if b"\x00" in data: continue
                    data.decode("utf-8")
                except UnicodeError: continue
                except OSError: continue
                result.append(rel)
        return sorted(result)

    def _command(self, argv, cwd="."):
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv): raise ValueError("argv must be a nonempty string array")
        argv = list(argv)
        if argv[0] == "python": argv[0] = sys.executable
        rules = [[sys.executable if x and x[0] == "python" else x[0], *x[1:]] if x else x for x in self.command_rules]
        allowed = argv in rules
        if argv == [sys.executable, "-m", "pytest", "-q"]: allowed = True
        elif argv in (["python", "-m", "pytest", "-q"],): allowed = True
        if argv in ([sys.executable, "run_checks.py"], ["python", "run_checks.py"]):
            allowed = (self.repo / "run_checks.py").is_file()
        helper = None
        if argv[0] == sys.executable and len(argv) >= 2 and argv[1] in ("read_pdf.py", "read_source.py"):
            helper = argv[1]
            allowed = (self.repo / helper).is_file() and self._strict_helper_args(helper, argv[2:])
        if not allowed: raise ValueError("command is not allowed")
        wd = self._resolve(cwd, allow_dir=True)
        if not wd.is_dir(): raise ValueError("cwd must be a directory")
        if helper and wd != self.repo: raise ValueError("repository helper must run from repository root")
        if argv[0] == sys.executable and len(argv) == 4 and argv[1:] == ["-m", "pytest", "-q"] and wd != self.repo:
            raise ValueError("full pytest must run from the repository root")
        env = os.environ.copy()
        if self.key_env:
            for key in list(env):
                if key.lower() == self.key_env.lower(): env.pop(key, None)
        for k in list(env):
            if k.upper().endswith("_API_KEY"): env.pop(k, None)
        timed_out = False
        proc = None
        try:
            proc = subprocess.Popen(argv, cwd=wd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}))
            try: out, err = proc.communicate(timeout=self.command_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._kill(proc); out, err = proc.communicate()
                err += b"\ncommand timed out"
        except KeyboardInterrupt:
            if proc is not None:
                self._kill(proc); out, err = proc.communicate()
                self.log("command_result", argv=argv, cwd=str(wd), rc=proc.returncode, stdout=out.decode("utf-8", "replace"), stderr=err.decode("utf-8", "replace"), interrupted=True, timed_out=False)
            raise
        stdout, stderr = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
        self.log("command_result", argv=argv, cwd=str(wd), rc=proc.returncode, stdout=stdout, stderr=stderr, timed_out=timed_out)
        return {"argv": argv, "cwd": str(wd), "rc": proc.returncode, "stdout": stdout, "stderr": stderr, "timed_out": timed_out}

    @staticmethod
    def _kill(proc):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, shell=False, check=False)
                if proc.poll() is None: proc.kill()
            else: os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            try: proc.kill()
            except OSError: pass

    def _strict_helper_args(self, name, args):
        if name == "read_pdf.py":
            # argparse-style: --start-page N [--end-page N] [--pdf PATH]
            if len(args) not in (2, 4, 6): return False
            i = 0; seen = set(); values = {}
            while i < len(args):
                key = args[i]
                if key not in ("--start-page", "--end-page", "--pdf") or key in seen: return False
                seen.add(key)
                if key in ("--start-page", "--end-page"):
                    if i + 1 >= len(args) or not args[i + 1].isdigit(): return False
                    values[key] = int(args[i + 1])
                    i += 2
                elif key == "--pdf":
                    if i + 1 >= len(args): return False
                    try: self._resolve(args[i + 1])
                    except (ValueError, OSError): return False
                    i += 2
                else: return False
            return "--start-page" in seen and ("--end-page" not in seen or values["--end-page"] >= values["--start-page"])
        # Exact read_source.py argparse grammar: --file PATH, then one of
        # --search TEXT or --start-line N, optionally --lines N (default 40).
        if len(args) < 2 or args[0] != "--file": return False
        try: self._resolve(args[1])
        except (ValueError, OSError): return False
        seen = set()
        i = 2
        while i < len(args):
            flag = args[i]
            if flag not in ("--search", "--start-line", "--lines") or flag in seen or i + 1 >= len(args): return False
            if flag in ("--search", "--start-line") and seen.intersection({"--search", "--start-line"}): return False
            value = args[i + 1]
            if flag == "--search":
                if not value: return False
            elif not value.isdigit(): return False
            elif flag == "--lines" and not 1 <= int(value) <= 120: return False
            elif flag == "--start-line" and int(value) < 1: return False
            seen.add(flag); i += 2
        return True

    def invoke(self, name, arguments):
        if name not in TOOL_SPECS: raise ValueError("unknown tool")
        if not isinstance(arguments, dict): raise ValueError("arguments must be an object")
        schema = TOOL_SPECS[name]["parameters"]
        if set(arguments) - set(schema["properties"]) or set(schema["required"]) - set(arguments): raise ValueError("invalid tool arguments")
        self._validate_schema_value(arguments, schema)
        if name == "list_files":
            limit, offset = arguments.get("limit", 200), arguments.get("offset", 0)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000 or not isinstance(offset, int) or offset < 0: raise ValueError("invalid pagination")
            files = self._files(arguments.get("path", ".")); return {"files": files[offset:offset + limit], "offset": offset, "limit": limit}
        if name == "search_code":
            q = arguments["query"]
            if not q: raise ValueError("query cannot be empty")
            limit = arguments.get("limit", 20)
            if not isinstance(limit, int) or not 1 <= limit <= 200: raise ValueError("invalid limit")
            if arguments.get("paths") is None:
                candidates = self._files(".")
            else:
                candidates = []
                for base in arguments["paths"]:
                    resolved = self._resolve(base, allow_dir=True)
                    if resolved.is_dir(): candidates.extend(self._files(base))
                    elif resolved.is_file(): candidates.append(self._norm_rel(base))
                candidates = sorted(set(candidates))
            hits = []
            for rel in candidates:
                try: _, content, _ = self._read(rel)
                except (OSError, ValueError): continue
                for n, line in enumerate(content.splitlines(), 1):
                    if q in line:
                        hits.append({"path": rel, "line": n, "start_line": n, "end_line": n, "content": line})
                        if len(hits) >= limit: return {"matches": hits}
            return {"matches": hits}
        if name == "read_file":
            p, c, h = self._read(arguments["path"]); return self._result_read(self._norm_rel(arguments["path"]), c, h)
        if name == "read_range":
            a, b = arguments["start_line"], arguments["end_line"]
            if not isinstance(a, int) or not isinstance(b, int) or a < 1 or b < a: raise ValueError("invalid line range")
            rel = self._norm_rel(arguments["path"]); _, content, digest = self._read(rel); lines = content.splitlines(keepends=True)
            if a > len(lines): raise ValueError("start_line is beyond end of file")
            actual_end = min(b, len(lines)); return self._result_read(rel, "".join(lines[a - 1:actual_end]), digest, start_line=a, end_line=actual_end)
        if name == "read_symbol":
            rel = self._norm_rel(arguments["path"]); _, content, digest = self._read(rel)
            tree = ast.parse(content); names = arguments["symbol"].split(".")
            if not all(names): raise ValueError("invalid qualified symbol")
            scope, n = tree.body, None
            for part in names:
                matches = [item for item in scope if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and item.name == part]
                if len(matches) != 1: raise ValueError("symbol not found or ambiguous")
                n = matches[0]; scope = n.body if isinstance(n, ast.ClassDef) else []
            start = min([n.lineno] + [d.lineno for d in n.decorator_list]); text = "".join(content.splitlines(keepends=True)[start - 1:n.end_lineno])
            return self._result_read(rel, text, digest, start_line=start, end_line=n.end_lineno)
        if name == "write_file": return self._write(arguments["path"], arguments["content"], arguments["expected_hash"])
        if name == "replace_text":
            rel = self._check_editable(arguments["path"]); _, content, digest = self._read(rel)
            if digest != arguments["expected_hash"]: raise ValueError("file hash changed; reread before writing")
            old = arguments["old_text"]
            if not old or content.count(old) != 1: raise ValueError("old_text must occur exactly once")
            return self._write(rel, content.replace(old, arguments["new_text"]), digest)
        if name == "read_pdf":
            start, end = arguments["start_page"], arguments.get("end_page")
            if not isinstance(start, int) or start < 1 or (end is not None and (not isinstance(end, int) or end < start)): raise ValueError("invalid PDF page range")
            args = ["python", "read_pdf.py", "--start-page", str(start)]
            if end is not None: args += ["--end-page", str(end)]
            result = self._command(args, ".")
            if result["rc"] != 0: raise OSError(f"read_pdf.py failed with rc={result['rc']}")
            try: parsed = json.loads(result["stdout"])
            except json.JSONDecodeError as exc: raise ValueError("read_pdf.py did not return valid JSON") from exc
            if not isinstance(parsed, dict): raise ValueError("read_pdf.py JSON result must be an object")
            result.update(parsed)
            return result
        return self._command(arguments["argv"], arguments.get("cwd", "."))

    @classmethod
    def _validate_schema_value(cls, value, schema):
        kind = schema.get("type")
        valid = {
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
        }.get(kind, lambda _v: True)
        if not valid(value): raise ValueError(f"expected {kind}")
        if kind == "object":
            props = schema.get("properties", {})
            if schema.get("additionalProperties") is False and set(value) - set(props): raise ValueError("additional properties are not allowed")
            if set(schema.get("required", [])) - set(value): raise ValueError("required property is missing")
            for key, item in value.items():
                if key in props: cls._validate_schema_value(item, props[key])
        elif kind == "array" and "items" in schema:
            for item in value: cls._validate_schema_value(item, schema["items"])

    def write_patch(self):
        """Export the editable snapshot diff.

        Empty-file creation uses a Git extended-diff header, so that artifact
        must be applied with ``git apply``; GNU unified-diff tools are not
        claimed to create that empty file.
        """
        chunks = []
        for rel in sorted(self._snapshot):
            old = self._snapshot[rel]
            try: _, new, _ = self._read(rel)
            except FileNotFoundError: new = None
            if old == new: continue
            before = (old or "").splitlines(keepends=True); after = (new or "").splitlines(keepends=True)
            if old is None and new == "":
                # Unified diff has no hunk for an empty file, so preserve its
                # creation as a Git extended diff artifact.
                diff = [f"diff --git a/{rel} b/{rel}\n", "new file mode 100644\n",
                        "--- /dev/null\n", f"+++ b/{rel}\n"]
            elif old == "" and new is None:
                diff = [f"diff --git a/{rel} b/{rel}\n", "deleted file mode 100644\n",
                        f"--- a/{rel}\n", "+++ /dev/null\n"]
            else:
                fromfile = "/dev/null" if old is None else "a/" + rel
                tofile = "/dev/null" if new is None else "b/" + rel
                diff = list(difflib.unified_diff(before, after, fromfile=fromfile, tofile=tofile))
            for i, line in enumerate(diff):
                if line.startswith(("-", "+")) and not line.startswith(("---", "+++")) and not line.endswith(("\n", "\r")):
                    diff[i] = line + "\n\\ No newline at end of file\n"
            chunks.extend(diff)
        self.output.mkdir(parents=True, exist_ok=True)
        target = self.output / "patch.diff"
        target.write_text("".join(chunks), encoding="utf-8", newline="")
        return target
