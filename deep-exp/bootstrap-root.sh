#!/bin/bash
# OS-level packages for DeepStruggle builds. Run as root. Idempotent.
# clang/llvm/lld: the engine is clang-only (CMake refuses GCC).
# g++: provides the libstdc++ development files clang++ links against.
set -euo pipefail
apt-get update
apt-get install -y clang llvm lld g++
clang++ -print-file-name=libstdc++.so >/dev/null && echo "libstdc++ OK"
clang --version | head -1
