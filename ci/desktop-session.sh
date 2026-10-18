#!/usr/bin/env bash
set -euo pipefail

# A window manager makes gtk3 frame resize requests deterministic under Xvfb.
openbox > /results/window-manager.log 2>&1 &
manager=$!
trap 'kill "$manager" 2>/dev/null || true; wait "$manager" 2>/dev/null || true' EXIT
ready=false
for attempt in {1..100}; do
    if xprop -root _NET_SUPPORTING_WM_CHECK | grep -q 'window id'; then
        ready=true
        break
    fi
    sleep 0.1
done
if [ "$ready" != true ]; then
    echo 'The private Xvfb window manager did not become ready' >&2
    exit 1
fi
runner=/work/tests/integration/run.py
if [[ " $* " == *" --soak "* ]]; then
    runner=/work/tests/integration/soak.py
fi
/opt/lo/program/python "$runner" \
    --program /opt/lo/program --oxt /packages/extension.oxt --output /results "$@"
