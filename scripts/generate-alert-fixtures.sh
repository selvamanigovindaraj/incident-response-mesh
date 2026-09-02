#!/usr/bin/env bash
set -eo pipefail

mkdir -p tests/fixtures/alerts

echo "==> Triggering Failure to Generate Alerts <=="
# Ensure victim app is running first
kubectl scale deploy/frontend-proxy --replicas=0 -n victim

echo "Waiting for Alertmanager to fire (this may take up to 2 minutes)..."
ECHO_POD=$(kubectl get pod -l app=alert-echo -n monitoring -o jsonpath='{.items[0].metadata.name}')

# Stream the echo server logs, looking for the payload indicator, capture next line
kubectl logs -f $ECHO_POD -n monitoring | awk '
  /--- ALERT PAYLOAD RECEIVED ---/ { flag=1; next }
  /------------------------------/ { flag=0; exit }
  flag { print > "tests/fixtures/alerts/KubeDeploymentReplicasMismatch.json" }
'

if [ -s "tests/fixtures/alerts/KubeDeploymentReplicasMismatch.json" ]; then
  echo "✅ Alert successfully captured!"
else
  echo "❌ Failed to capture alert payload."
  exit 1
fi

echo "Restoring victim environment..."
kubectl scale deploy/frontend-proxy --replicas=1 -n victim
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=frontend-proxy -n victim --timeout=2m

echo "==> Fixture Generation Complete <=="
