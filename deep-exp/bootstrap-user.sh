#!/bin/bash
# User-level bootstrap. Usage: bootstrap-user.sh <workspace-dir>
# Installs uv, a Python 3.14 venv with CUDA torch + repo requirements, and
# clones this branch. Safe to re-run; skips finished steps.
set -euo pipefail
WS="${1:?usage: bootstrap-user.sh <workspace-dir>}"
mkdir -p "$WS/logs"
exec > >(tee -a "$WS/logs/bootstrap.log") 2>&1
echo "=== bootstrap start $(date -u) ==="

if [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

if [ ! -x "$WS/venv/bin/python" ]; then
  uv venv --python 3.14 "$WS/venv"
fi

# CUDA torch first (per-platform wheels), then the repo requirements on top.
if ! "$WS/venv/bin/python" -c "import torch" 2>/dev/null; then
  uv pip install --python "$WS/venv/bin/python" torch \
    --index-url https://download.pytorch.org/whl/cu130
fi

if [ ! -d "$WS/DeepStruggle/.git" ]; then
  git clone --branch experiment/deep-from-scratch \
    https://github.com/artbristol/DeepStruggle.git "$WS/DeepStruggle"
fi
cd "$WS/DeepStruggle"
echo "checked out $(git rev-parse HEAD) ($(git rev-parse --abbrev-ref HEAD))"

uv pip install --python "$WS/venv/bin/python" -r requirements.txt
"$WS/venv/bin/python" -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
echo "=== bootstrap done $(date -u); next: cmake build + gate (see deep-exp/RUNBOOK.md) ==="
