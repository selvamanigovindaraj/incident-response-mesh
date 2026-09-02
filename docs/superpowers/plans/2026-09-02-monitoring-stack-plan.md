# Monitoring Stack Implementation Plan

This plan implements the monitoring stack and alert generation framework detailed in the design spec.

## Dependencies
- k3d cluster must be running (`make cluster-up`)
- The victim app should be deployable (`make victim-up`) to generate traces, though the monitoring stack operates independently.

---

### Task 1: Create the Alert Echo Webhook Receiver
Create the deployment and service manifests for a lightweight HTTP server to echo Alertmanager JSON payloads.

**Files:**
- Create: `infra/monitoring/alert-echo.yaml`

**Interfaces:**
- Produces: A Kubernetes Service named `alert-echo` exposing port `8080`.

- [ ] **Step 1: Write `infra/monitoring/alert-echo.yaml`**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alert-echo
  namespace: monitoring
  labels:
    app: alert-echo
spec:
  replicas: 1
  selector:
    matchLabels:
      app: alert-echo
  template:
    metadata:
      labels:
        app: alert-echo
    spec:
      containers:
      - name: python-echo
        image: python:3.11-alpine
        # A tiny python server that prints the POST body to stdout
        command: ["python3", "-c"]
        args:
        - |
          import http.server
          class EchoHandler(http.server.BaseHTTPRequestHandler):
              def do_POST(self):
                  content_len = int(self.headers.get('Content-Length', 0))
                  post_body = self.rfile.read(content_len)
                  print("--- ALERT PAYLOAD RECEIVED ---")
                  print(post_body.decode('utf-8'))
                  print("------------------------------")
                  self.send_response(200)
                  self.end_headers()
          http.server.HTTPServer(('', 8080), EchoHandler).serve_forever()
        ports:
        - containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: alert-echo
  namespace: monitoring
spec:
  selector:
    app: alert-echo
  ports:
    - protocol: TCP
      port: 8080
      targetPort: 8080
```

- [ ] **Step 2: Commit**
```bash
git add infra/monitoring/alert-echo.yaml
git commit -m "infra: add alert-echo webhook receiver"
```

---

### Task 2: Create Base Monitoring Helm Values
Create the Helm values for `kube-prometheus-stack` to handle scraping, Ingress (Grafana/Alertmanager/Prometheus), and Alertmanager routing.

**Files:**
- Create: `infra/monitoring/values-local.yaml`

**Interfaces:**
- Produces: Base Helm configuration for Prometheus, Alertmanager, and Grafana.

- [ ] **Step 1: Write `infra/monitoring/values-local.yaml`**
```yaml
grafana:
  enabled: true
  ingress:
    enabled: true
    ingressClassName: traefik
    hosts:
      - localhost
    path: /
  # Set default password for local development
  adminPassword: "prom-operator"

prometheus:
  prometheusSpec:
    # Scrape configuration for the victim namespace
    serviceMonitorSelectorNilUsesHelmValues: false
    podMonitorSelectorNilUsesHelmValues: false
    ruleSelectorNilUsesHelmValues: false
  ingress:
    enabled: true
    ingressClassName: traefik
    hosts:
      - localhost
    paths:
      - /

alertmanager:
  config:
    global:
      resolve_timeout: 1m
    route:
      group_by: ['namespace']
      group_wait: 10s
      group_interval: 10s
      repeat_interval: 1h
      receiver: 'echo-webhook'
    receivers:
    - name: 'null'
    - name: 'echo-webhook'
      webhook_configs:
      - url: 'http://alert-echo.monitoring.svc.cluster.local:8080/'
  ingress:
    enabled: true
    ingressClassName: traefik
    hosts:
      - localhost
    paths:
      - /
```

- [ ] **Step 2: Verify YAML**
Run `cat infra/monitoring/values-local.yaml` to verify the structure.

- [ ] **Step 3: Commit**
```bash
git add infra/monitoring/values-local.yaml
git commit -m "infra: add base helm values for kube-prometheus-stack"
```

---

### Task 3: Inject Curated Alert Rules
Append the required curated alert rules into the `values-local.yaml`.

**Files:**
- Modify: `infra/monitoring/values-local.yaml`

**Interfaces:**
- Consumes: `infra/monitoring/values-local.yaml`
- Produces: Evaluated Prometheus alerts under the `additionalPrometheusRulesMap` key.

- [ ] **Step 1: Append Rules to `infra/monitoring/values-local.yaml`**
Append this exact block to the end of the file:
```yaml
additionalPrometheusRulesMap:
  rule-name:
    groups:
      - name: custom-victim-alerts
        rules:
          - alert: KubePodCrashLooping
            expr: rate(kube_pod_container_status_restarts_total{namespace="victim"}[5m]) * 60 * 5 > 0
            for: 30s # Production: 5m
            labels:
              severity: critical
            annotations:
              summary: "Pod is crash looping."
              description: "Pod {{ $labels.namespace }}/{{ $labels.pod }} ({{ $labels.container }}) is restarting repeatedly."

          - alert: TargetDown
            expr: up{namespace="victim"} == 0
            for: 30s # Production: 5m
            labels:
              severity: critical
            annotations:
              summary: "Target down"
              description: "{{ $labels.instance }} has been down for more than 30s."

          - alert: HighErrorRate
            # Assuming typical istio/envoy or standard 5xx metric (mocked for demo if needed, but matching common forms)
            expr: sum(rate(http_requests_total{status=~"5..", namespace="victim"}[2m])) / sum(rate(http_requests_total{namespace="victim"}[2m])) > 0.05
            for: 30s # Production: 5m
            labels:
              severity: critical
            annotations:
              summary: "High HTTP 5xx error rate"
              description: "More than 5% of requests are failing in {{ $labels.namespace }}."

          - alert: MemorySaturation
            expr: container_memory_working_set_bytes{namespace="victim"} / container_spec_memory_limit_bytes{namespace="victim"} > 0.85
            for: 1m # Production: 5m
            labels:
              severity: warning
            annotations:
              summary: "Memory saturation approaching limit"
              description: "Pod {{ $labels.pod }} is using over 85% of its memory limit."
              
          - alert: KubeDeploymentReplicasMismatch
            expr: kube_deployment_spec_replicas{namespace="victim"} != kube_deployment_status_replicas_available{namespace="victim"}
            for: 30s # Production: 5m
            labels:
              severity: warning
            annotations:
              summary: "Deployment Replicas Mismatch"
              description: "Deployment {{ $labels.deployment }} has missing replicas."
```

- [ ] **Step 2: Commit**
```bash
git add infra/monitoring/values-local.yaml
git commit -m "infra: inject curated alert rules to monitoring stack"
```

---

### Task 4: Add Monitoring Makefile Targets
Add `monitoring-up` and `monitoring-down` to the Makefile.

**Files:**
- Modify: `Makefile`

**Interfaces:**
- Produces: Makefile commands to spin the stack up and down.

- [ ] **Step 1: Append to `Makefile`**
Ensure REAL TABS are used for indentation.

```makefile

.PHONY: monitoring-up
monitoring-up: check-prereqs
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
	helm repo update prometheus-community
	helm upgrade --install prometheus prometheus-community/kube-prometheus-stack --version 62.3.1 \
		--namespace monitoring --create-namespace \
		-f infra/monitoring/values-local.yaml
	kubectl apply -f infra/monitoring/alert-echo.yaml
	@echo "Waiting for monitoring pods to be Ready..."
	kubectl wait --for=condition=ready pod -l app.kubernetes.io/instance=prometheus -n monitoring --timeout=5m
	kubectl wait --for=condition=ready pod -l app=alert-echo -n monitoring --timeout=2m

.PHONY: monitoring-down
monitoring-down: check-prereqs
	helm uninstall prometheus -n monitoring || true
	kubectl delete namespace monitoring --ignore-not-found
```

- [ ] **Step 2: Dry Run Check**
Run `make -n monitoring-up` to verify syntax.

- [ ] **Step 3: Commit**
```bash
git add Makefile
git commit -m "infra: add make targets for monitoring up and down"
```

---

### Task 5: Write the Fixture Generation Script
Create a bash script to induce a failure, wait for an alert, capture it, and restore the system.

**Files:**
- Create: `scripts/generate-alert-fixtures.sh`
- Create: `tests/fixtures/alerts/` (directory)

**Interfaces:**
- Produces: An executable bash script that outputs JSON to `tests/fixtures/alerts/`.

- [ ] **Step 1: Write `scripts/generate-alert-fixtures.sh`**
```bash
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
```

- [ ] **Step 2: Make executable**
`chmod +x scripts/generate-alert-fixtures.sh`

- [ ] **Step 3: Add to Makefile**
Append to `Makefile`:
```makefile

.PHONY: generate-fixtures
generate-fixtures: check-prereqs
	./scripts/generate-alert-fixtures.sh
```

- [ ] **Step 4: Commit**
```bash
git add scripts/generate-alert-fixtures.sh Makefile
git commit -m "test: add alert fixture generation script"
```
