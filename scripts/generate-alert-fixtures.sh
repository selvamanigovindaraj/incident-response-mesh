#!/usr/bin/env bash
set -eo pipefail

mkdir -p tests/fixtures/alerts

echo "==> Triggering Failure to Generate Alerts <=="
# We trigger a replicas mismatch by specifying a broken image, 
# which causes ImagePullBackOff (available=0, spec=1).
kubectl set image deploy/frontend-proxy frontend-proxy="nginx:invalid-tag-123" -n victim

echo "Waiting for Alertmanager to fire (this may take up to 3 minutes)..."
ECHO_POD=$(kubectl get pod -l app=alert-echo -n monitoring --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')

# We use timeout so this doesn't hang forever if it fails
timeout 180 awk '
  /--- ALERT PAYLOAD RECEIVED ---/ { flag=1; next }
  /------------------------------/ { flag=0; exit }
  flag { print > "tests/fixtures/alerts/KubeDeploymentReplicasMismatch.json" }
' <(kubectl logs -f $ECHO_POD -n monitoring) || true

if [ -s "tests/fixtures/alerts/KubeDeploymentReplicasMismatch.json" ]; then
  echo "✅ Alert successfully captured!"
else
  echo "❌ Failed to capture alert payload."
  # Restore immediately on failure
  kubectl rollout undo deploy/frontend-proxy -n victim
  exit 1
fi

echo "Restoring victim environment..."
kubectl rollout undo deploy/frontend-proxy -n victim
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=frontend-proxy -n victim --timeout=2m

echo "==> Fixture Generation Complete <=="
