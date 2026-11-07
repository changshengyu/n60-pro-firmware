#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$root/logs"
cd "$root/build"
python3 "$root/scripts/validate.py" config
make download -j4 V=s 2>&1 | tee "$root/logs/download.log"
if ! make -j"${BUILD_JOBS:-2}" V=s 2>&1 | tee "$root/logs/build.log"; then
  echo 'Parallel build failed. Retrying once serially for a complete diagnosis.'
  make -j1 V=s 2>&1 | tee "$root/logs/build-retry.log"
fi
python3 "$root/scripts/validate.py" kernel
python3 "$root/scripts/collect.py"
