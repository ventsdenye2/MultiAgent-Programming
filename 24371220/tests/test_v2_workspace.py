import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from codeagent.workspace import WorkspaceTools, TOOL_SPECS


@pytest.fixture
def ws(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mod.py").write_text("@decorate\nclass Box:\n    @decorate\n    def target(self):\n        return 1\n", encoding="utf-8", newline="")
    (repo / "note.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8", newline="")
    (repo / "crlf.txt").write_text("alpha\r\nbeta\r\ngamma\r\n", encoding="utf-8", newline="")
    events = []
    obj = WorkspaceTools(repo, tmp_path / "out", {"mod.py", "note.txt"}, lambda event, **fields: events.append((event, fields)))
    return obj, repo, events


def test_specs_and_reads_are_logged(ws):
    obj, _, events = ws
    assert set(TOOL_SPECS) >= {"read_file", "read_range", "read_symbol"}
    full = obj.invoke("read_file", {"path": "note.txt"})
    assert full["content"] == "alpha\nbeta\ngamma\n"
    assert obj.invoke("read_range", {"path": "crlf.txt", "start_line": 2, "end_line": 3})["content"] == "beta\r\ngamma\r\n"
    symbol = obj.invoke("read_symbol", {"path": "mod.py", "symbol": "Box.target"})
    assert symbol["content"].startswith("    @decorate") and symbol["end_line"] == 5
    reads = [fields for event, fields in events if event == "file_read"]
    assert reads[0]["content"] == full["content"]
    assert reads[-1]["start_line"] == 3 and reads[-1]["end_line"] == 5


def test_edit_requires_hash_and_unique_replace_and_patch(ws):
    obj, repo, _ = ws
    before = obj.current_hash("note.txt")
    with pytest.raises(ValueError):
        obj.invoke("write_file", {"path": "note.txt", "content": "x", "expected_hash": "stale"})
    result = obj.invoke("replace_text", {"path": "note.txt", "old_text": "beta", "new_text": "BETA", "expected_hash": before})
    assert result["changed"] and result["before_hash"] == before
    patch = obj.write_patch()
    assert "-beta" in patch.read_text(encoding="utf-8")
    assert (repo / "note.txt").read_text(encoding="utf-8").find("BETA") >= 0
    (repo / "note.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8", newline="")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    checked = subprocess.run(["git", "-C", str(repo), "apply", "--check", str(patch)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr


def test_hidden_secret_and_symlink_escape_rejected(ws, tmp_path):
    obj, repo, _ = ws
    (repo / ".env").write_text("private", encoding="utf-8")
    (repo / ".hidden").write_text("hidden", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        (repo / "escape.txt").symlink_to(outside)
    except OSError:
        pytest.skip("Windows symlink privilege is unavailable")
    assert ".env" not in obj.invoke("list_files", {})["files"]
    assert ".hidden" not in obj.invoke("list_files", {})["files"]
    with pytest.raises(ValueError): obj.invoke("read_file", {"path": "escape.txt"})
    with pytest.raises(ValueError): obj.invoke("read_file", {"path": "../outside.txt"})


def test_run_command_exact_rules_and_pdf_uses_helper(ws):
    obj, repo, events = ws
    (repo / "read_pdf.py").write_text("import json\nprint(json.dumps({'pages':[1]}))\n", encoding="utf-8")
    result = obj.invoke("read_pdf", {"start_page": 1})
    assert result["pages"] == [1] and result["stdout"].strip() == '{"pages": [1]}'
    assert result["argv"][1] == "read_pdf.py"
    with pytest.raises(ValueError): obj.invoke("run_command", {"argv": ["python", "-c", "print(1)"]})
    result = obj.invoke("run_command", {"argv": ["python", "-m", "pytest", "-q"]})
    assert result["argv"][0] == sys.executable
    assert any(ev == "command_result" for ev, _ in events)
    outside = repo.parent / "read_pdf.py"
    outside.write_text("raise SystemExit(0)\n", encoding="utf-8")
    with pytest.raises(ValueError):
        obj.invoke("run_command", {"argv": [sys.executable, str(outside), "--start-page", "1"]})


def test_read_source_arguments_are_strict(ws):
    obj, repo, _ = ws
    (repo / "read_source.py").write_text("import json\nprint(json.dumps({'ok': True}))\n", encoding="utf-8")
    valid = [sys.executable, "read_source.py", "--file", "note.txt", "--search", "beta", "--lines", "4"]
    assert obj.invoke("run_command", {"argv": valid})["rc"] == 0
    for invalid in (
        valid + ["--search", "again"],
        [sys.executable, "read_source.py", "--file", "../outside.txt", "--start-line", "1"],
        [sys.executable, "read_source.py", "--file", "note.txt", "--search", "beta", "--start-line", "1"],
    ):
        with pytest.raises(ValueError): obj.invoke("run_command", {"argv": invalid})


def test_command_rule_and_hash_missing(ws):
    obj, repo, _ = ws
    obj.command_rules.append([sys.executable, "-c", "print('allowed')"])
    assert obj.invoke("run_command", {"argv": [sys.executable, "-c", "print('allowed')"]})["stdout"].strip() == "allowed"
    assert obj.current_hash("does-not-exist") == "missing"
    (repo / "new.txt").write_text("", encoding="utf-8")
    # Snapshot an authorized path that does not yet exist, then create an empty file.
    fresh = WorkspaceTools(repo, obj.output, {"new-empty.txt"}, lambda *_a, **_k: None)
    created = fresh.invoke("write_file", {"path": "new-empty.txt", "content": "", "expected_hash": "missing"})
    assert created["changed"] and (repo / "new-empty.txt").exists()
    empty_artifact = fresh.write_patch()
    empty_diff = empty_artifact.read_text(encoding="utf-8")
    assert "diff --git a/new-empty.txt b/new-empty.txt" in empty_diff
    assert "new file mode 100644" in empty_diff
    assert "--- /dev/null\n+++ b/new-empty.txt\n" in empty_diff
    assert "@@" not in empty_diff
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "new-empty.txt").unlink()
    checked_empty = subprocess.run(["git", "-C", str(repo), "apply", "--check", str(empty_artifact)], capture_output=True, text=True)
    assert checked_empty.returncode == 0, checked_empty.stderr
    ordinary = WorkspaceTools(repo, obj.output / "ordinary", {"new-ordinary.txt"}, lambda *_a, **_k: None)
    ordinary.invoke("write_file", {"path": "new-ordinary.txt", "content": "new file", "expected_hash": "missing"})
    ordinary_diff = ordinary.write_patch().read_text(encoding="utf-8")
    assert "--- /dev/null\n+++ b/new-ordinary.txt\n" in ordinary_diff
    assert "\\ No newline at end of file" in ordinary_diff
    with pytest.raises(ValueError): fresh.invoke("list_files", {"limit": True})
    with pytest.raises(ValueError): fresh.invoke("read_pdf", {"start_page": True})


def test_current_hash_handles_binary_and_large_files_without_relaxing_text_reads(ws, monkeypatch):
    obj, repo, _ = ws
    binary_path = repo / "sample.pdf"
    binary = b"%PDF-1.7\x00\xffbinary payload"
    binary_path.write_bytes(binary)
    first = hashlib.sha256(binary).hexdigest()
    assert obj.current_hash("sample.pdf") == first
    with pytest.raises(ValueError):
        obj.invoke("read_file", {"path": "sample.pdf"})
    changed = binary + b"changed"
    binary_path.write_bytes(changed)
    assert obj.current_hash("sample.pdf") == hashlib.sha256(changed).hexdigest()

    large_path = repo / "large.pdf"
    large = b"%PDF-1.7\x00" + (b"x" * (2 * 1024 * 1024))
    large_path.write_bytes(large)
    assert obj.current_hash("large.pdf") == hashlib.sha256(large).hexdigest()
    with pytest.raises(ValueError):
        obj.invoke("read_file", {"path": "large.pdf"})

    assert obj.current_hash("not-there.pdf") == "missing"
    with pytest.raises(OSError):
        obj.current_hash(".")
    with pytest.raises(ValueError):
        obj.current_hash("../outside.pdf")

    real_open = Path.open
    def denied_open(path, *args, **kwargs):
        if path == binary_path:
            raise PermissionError("access denied")
        return real_open(path, *args, **kwargs)
    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "open", denied_open)
        with pytest.raises(PermissionError):
            obj.current_hash("sample.pdf")


def test_diff_marks_eof_without_newline_and_applies(ws):
    obj, repo, _ = ws
    (repo / "note.txt").write_text("old", encoding="utf-8", newline="")
    obj = WorkspaceTools(repo, obj.output, {"note.txt"}, lambda *_a, **_k: None)
    obj.invoke("replace_text", {"path": "note.txt", "old_text": "old", "new_text": "new", "expected_hash": obj.current_hash("note.txt")})
    patch = obj.write_patch()
    patch_text = patch.read_text(encoding="utf-8")
    assert patch_text.count("\\ No newline at end of file") == 2
    (repo / "note.txt").write_text("old", encoding="utf-8", newline="")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    checked = subprocess.run(["git", "-C", str(repo), "apply", "--check", str(patch)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr


def test_empty_file_deletion_uses_git_extended_diff(ws):
    obj, repo, _ = ws
    path = repo / "empty-delete.txt"
    path.write_text("", encoding="utf-8", newline="")
    obj = WorkspaceTools(repo, obj.output, {"empty-delete.txt"}, lambda *_a, **_k: None)
    path.unlink()
    patch = obj.write_patch()
    patch_text = patch.read_text(encoding="utf-8")
    assert "deleted file mode 100644" in patch_text
    assert "--- a/empty-delete.txt\n+++ /dev/null\n" in patch_text
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    path.write_text("", encoding="utf-8", newline="")
    checked = subprocess.run(["git", "-C", str(repo), "apply", "--check", str(patch)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr
