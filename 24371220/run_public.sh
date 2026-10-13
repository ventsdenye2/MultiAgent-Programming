#!/usr/bin/env bash
set -euo pipefail
submission="$(cd "$(dirname "$0")" && pwd)"
course="$(dirname "$submission")"
if [[ $# -ne 1 ]]; then
  echo '用法：bash 24371220/run_public.sh 新轮次名（例如 attempt05）' >&2
  exit 2
fi
if [[ ! "$1" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo '轮次名只允许字母、数字、下划线和连字符' >&2
  exit 2
fi
if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  read -rsp 'DeepSeek API Key: ' DEEPSEEK_API_KEY
  echo
  export DEEPSEEK_API_KEY
fi
export TMPDIR="$submission/experiments/linux_tmp"
mkdir -p "$TMPDIR"
mounted_here=0
if ! mountpoint -q "$TMPDIR"; then
  sudo mount -t tmpfs -o size=256M,mode=1777 tmpfs "$TMPDIR"
  mounted_here=1
fi
cleanup() {
  if [[ "$mounted_here" == 1 ]]; then
    sudo umount "$TMPDIR"
  fi
}
trap cleanup EXIT
cd "$course"
"$submission/.venv/bin/python" run_eval.py --agent "$submission/agent.py" \
  --out "$submission/experiments/public/$1"
