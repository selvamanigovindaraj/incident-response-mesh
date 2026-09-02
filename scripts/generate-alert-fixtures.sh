#!/usr/bin/env bash
set -eo pipefail

mkdir -p tests/fixtures/alerts

echo "==> Triggering Failure to Generate Alerts <=="
kubectl set image deploy/frontend-proxy frontend-proxy="nginx:invalid-tag-123" -n victim

echo "Waiting for Alertmanager to fire (this may take up to 3 minutes)..."
ECHO_POD=$(kubectl get pod -l app=alert-echo -n monitoring | grep Running | awk '{print $1}' | head -n 1)
echo "Streaming logs from ${ECHO_POD}..."

timeout 180 awk '
  /--- ALERT PAYLOAD RECEIVED ---/ { flag=1; next }
  /------------------------------/ { flag=0; exit }
  flag { print > "tests/fixtures/alerts/KubeDeploymentReplicasMismatch.json" }
' <(kubectl logs -f $ECHO_POD -n monitoring) || true

if [ -s "tests/fixtures/alerts/KubeDeploymentReplicasMismatch.json" ]; then
  echo "✅ Alert successfully captured!"
else
  echo "❌ Failed to capture alert payload."
  kubectl rollout undo deploy/frontend-proxy -n victim
  exit 1
fi

echo "Restoring victim environment..."
kubectl rollout undo deploy/frontend-proxy -n victim
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=frontend-proxy -n victim --timeout=2m

echo "==> Fixture Generation Complete <=="
