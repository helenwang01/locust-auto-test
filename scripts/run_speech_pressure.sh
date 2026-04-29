#!/usr/bin/env bash
set -euo pipefail

# One-click speech transcription pressure test.
# Usage:
#   scripts/run_speech_pressure.sh [USERS] [SPAWN_RATE] [DURATION] [TARGET_QPS] [SHAPE_HOLD_SECONDS]
# Example:
#   scripts/run_speech_pressure.sh 20 5 5m 100 300

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

USERS="${1:-20}"
SPAWN_RATE="${2:-5}"
DURATION="${3:-5m}"
TARGET_QPS="${4:-0}"
SHAPE_HOLD_SECONDS="${5:-0}"
OUT_PREFIX="out/speech_transcriptions"

mkdir -p out

echo "[speech-pressure] start: users=${USERS}, spawn_rate=${SPAWN_RATE}, duration=${DURATION}, target_qps=${TARGET_QPS}, shape_hold_seconds=${SHAPE_HOLD_SECONDS}"
echo "[speech-pressure] locustfile=loadtests/http/locustfile_speech_transcriptions.py"
echo "[speech-pressure] csv=${OUT_PREFIX}_*.csv"

locust \
  -f loadtests/http/locustfile_speech_transcriptions.py \
  --headless \
  -u "${USERS}" \
  -r "${SPAWN_RATE}" \
  -t "${DURATION}" \
  --target-qps "${TARGET_QPS}" \
  --shape-hold-seconds "${SHAPE_HOLD_SECONDS}" \
  --csv "${OUT_PREFIX}" \
  --loglevel INFO
