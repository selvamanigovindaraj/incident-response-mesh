#!/usr/bin/env bash
set -eo pipefail

echo "==> Running Victim Application Smoke Test <=="

echo "1. Checking Frontend Health..."
# Retry up to 5 times to allow Ingress routing to settle
for i in {1..5}; do
  if curl -s --fail http://localhost:8080/ > /dev/null; then
    echo "Frontend is healthy."
    break
  fi
  if [ $i -eq 5 ]; then
    echo "Frontend health check failed."
    exit 1
  fi
  sleep 2
done

echo "2. Checking Telemetry Flow in Jaeger..."
# Port-forward Jaeger query service in the background
kubectl port-forward svc/jaeger 16686:16686 -n victim > /dev/null 2>&1 &
PF_PID=$!

# Ensure we kill the port-forward on script exit
trap "kill $PF_PID 2>/dev/null || true" EXIT

# Wait for port-forward to establish
sleep 3

# Query Jaeger API for traces from the frontend service
TRACES=$(curl -s "http://localhost:16686/api/traces?service=frontend")
TRACE_COUNT=$(echo "$TRACES" | jq '.data | length')

if [ "$TRACE_COUNT" -gt 0 ]; then
  echo "Telemetry verified. Found $TRACE_COUNT traces for frontend."
else
  echo "Telemetry verification failed. No traces found."
  exit 1
fi

echo "3. Checking Failure State..."
kubectl scale deploy/opentelemetry-demo-frontend --replicas=0 -n victim
echo "Waiting for frontend to scale down..."
sleep 10

if curl -s --fail http://localhost:8080/ > /dev/null; then
  echo "Expected frontend to fail, but it succeeded!"
  exit 1
else
  echo "Frontend correctly failed when scaled to 0."
fi

echo "Restoring frontend..."
kubectl scale deploy/opentelemetry-demo-frontend --replicas=1 -n victim
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=frontend -n victim --timeout=2m

echo "==> Smoke Test Passed! <=="
