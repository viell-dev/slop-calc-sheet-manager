#!/usr/bin/env bash
set -euo pipefail
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
/opt/lo/program/python /lab/crash_lab.py --program /opt/lo/program \
    --oxt /packages/extension.oxt --output /results "$@"
