#!/usr/bin/env bash
set -euo pipefail
submission="$(cd "$(dirname "$0")" && pwd)"
python="$submission/.venv/bin/python"
"$python" -c 'import sys,pytest; assert sys.version_info[:2] == (3,12); print("Python/pytest ready")'
command -v patch >/dev/null
command -v pdftotext >/dev/null
export CODE_AGENT_ENGINE=v2
export MINI_CONTEXT_MODE=evidence
export TMPDIR="$submission/experiments/linux_tmp"
mkdir -p "$TMPDIR"
mounted_here=0
if ! mountpoint -q "$TMPDIR"; then
  sudo mount -t tmpfs -o size=256M,mode=1777 tmpfs "$TMPDIR"
  mounted_here=1
fi
cleanup() {
  if [[ "$mounted_here" == 1 ]]; then sudo umount "$TMPDIR"; fi
}
trap cleanup EXIT
"$python" "$submission/evaluate_long_context_v2.py"
