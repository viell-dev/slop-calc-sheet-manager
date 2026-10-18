#!/usr/bin/env bash
set -euo pipefail
unset WAYLAND_DISPLAY
mkdir -p /results "$HOME"
cp /opt/ci-metadata/* /results/
/opt/lo/program/soffice --version | tee /results/office-version.txt
/opt/lo/program/python -c 'import sys, uno; print(sys.version)' | tee /results/python-version.txt
exec xvfb-run --auto-servernum --server-args='-screen 0 1600x1000x24 -nolisten tcp' \
    dbus-run-session -- /opt/lo/program/python /work/tests/integration/run.py \
    --program /opt/lo/program --oxt /packages/extension.oxt --output /results "$@"
