#!/usr/bin/env bash
# Usage: run.sh NAME OXT [walk.py arguments...]  Starts one lab container; waits for 4 GiB free.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
LAB="${LAB:-$REPO/test-results/ordinary-use}"
name=$1; oxt=$2; shift 2
out="$LAB/results/$name"
mkdir -p "$out"; chmod 777 "$out"
until [ "$(free -b | awk '/^Mem:/ {print $7}')" -ge $((4 * 1024 * 1024 * 1024)) ]; do
    echo "waiting for 4 GiB available"; sleep 120
done
if docker ps --format '{{.Names}}' | grep -q '^sm-walk-'; then echo "another sm-walk container runs" >&2; exit 1; fi
free -h | sed -n 2p
exec docker run --rm --init --network none --shm-size 512m --name "sm-walk-$name" \
    --env HOME=/tmp/h --env PYTHONDONTWRITEBYTECODE=1 \
    --mount type=bind,source="$REPO",target=/work,readonly \
    --mount type=bind,source="$oxt",target=/packages/extension.oxt,readonly \
    --mount type=bind,source="$HERE",target=/harness,readonly \
    --mount type=bind,source="$out",target=/results \
    --entrypoint bash sheet-manager-lab:26.8.3.1 /harness/session.sh "$@"
