#!/usr/bin/env bash
set -euo pipefail
submission="$(cd "$(dirname "$0")" && pwd)"
export TMPDIR="$submission/experiments/feature_tmp"
mkdir -p "$TMPDIR"
mount -t tmpfs -o size=256M,mode=1777 tmpfs "$TMPDIR"
trap 'umount "$TMPDIR"' EXIT
"$submission/.venv/bin/python" "$submission/experiment.py"
