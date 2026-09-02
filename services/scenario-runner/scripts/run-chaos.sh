#!/usr/bin/env bash
set -eo pipefail

if [ -z "$1" ]; then
  echo "Usage: $0 <experiment-name>"
  exit 1
fi

EXP_FILE="chaos/experiments/$1.yaml"
if [ ! -f "$EXP_FILE" ]; then
  echo "❌ Error: Experiment file $EXP_FILE not found."
  exit 1
fi

# Extract duration string (e.g., '60s', '1m') using grep/awk
DURATION_STR=$(grep -E "^  duration: " "$EXP_FILE" | awk '{print $2}' | tr -d '"'\''')
if [ -z "$DURATION_STR" ]; then
  echo "❌ Error: Could not parse 'duration' from $EXP_FILE"
  exit 1
fi

# Very naive parsing for s or m
if [[ $DURATION_STR == *m ]]; then
  WAIT_TIME=$(( ${DURATION_STR%m} * 60 ))
elif [[ $DURATION_STR == *s ]]; then
  WAIT_TIME=${DURATION_STR%s}
else
  WAIT_TIME=$DURATION_STR
fi

echo "==> 🌪️ Starting Chaos Experiment: $1"
kubectl apply -f "$EXP_FILE"

echo "⏳ Waiting for ${WAIT_TIME} seconds..."
sleep "$WAIT_TIME"

echo "==> 🧹 Cleaning up Chaos Experiment: $1"
kubectl delete -f "$EXP_FILE"
echo "✅ Experiment complete and purged."
