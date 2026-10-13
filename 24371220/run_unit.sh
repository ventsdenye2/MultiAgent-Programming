#!/usr/bin/env bash
set -euo pipefail
submission="$(cd "$(dirname "$0")" && pwd)"
export TMPDIR="$submission/experiments/linux_unit_tmp"
mkdir -p "$TMPDIR"
sudo mount -t tmpfs -o size=128M,mode=1777 tmpfs "$TMPDIR"
trap 'sudo umount "$TMPDIR"' EXIT
cd "$submission"
"$submission/.venv/bin/python" -m pytest -q test_agent.py --basetemp "$TMPDIR/unit"
