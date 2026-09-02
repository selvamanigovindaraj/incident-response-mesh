.PHONY: check-prereqs
check-prereqs:
	@command -v docker >/dev/null 2>&1 || { echo >&2 "docker is required but not installed. Aborting."; exit 1; }
	@command -v k3d >/dev/null 2>&1 || { echo >&2 "k3d is required but not installed. Aborting."; exit 1; }
	@command -v kubectl >/dev/null 2>&1 || { echo >&2 "kubectl is required but not installed. Aborting."; exit 1; }
	@command -v helm >/dev/null 2>&1 || { echo >&2 "helm is required but not installed. Aborting."; exit 1; }
	@command -v jq >/dev/null 2>&1 || { echo >&2 "jq is required but not installed. Aborting."; exit 1; }
	@echo "All prerequisites found."

.PHONY: cluster-up
cluster-up: check-prereqs
	k3d cluster create --config infra/cluster/k3d.yaml

.PHONY: cluster-down
cluster-down: check-prereqs
	k3d cluster delete --config infra/cluster/k3d.yaml

.PHONY: cluster-status
cluster-status: check-prereqs
	k3d cluster list
	kubectl get nodes -o wide

.PHONY: test-registry
test-registry: check-prereqs
	@echo "Testing registry push..."
	docker pull alpine:latest
	docker tag alpine:latest localhost:5001/test-image:latest
	docker push localhost:5001/test-image:latest
	@echo "Testing registry pull from within cluster..."
	kubectl run registry-test --image=irm-registry:5000/test-image:latest --restart=Never --rm -i --tty -- sh -c "command -v sh"

.PHONY: victim-up
victim-up: check-prereqs
	helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
	helm repo update open-telemetry
	helm upgrade --install opentelemetry-demo open-telemetry/opentelemetry-demo --version 0.41.0 \
		--namespace victim --create-namespace \
		-f infra/victim/values-local.yaml
	@echo "Waiting for all pods in victim namespace to be Ready (this may take up to 10 minutes)..."
	kubectl wait --for=condition=ready pod --all -n victim --timeout=10m

.PHONY: victim-down
victim-down: check-prereqs
	helm uninstall opentelemetry-demo -n victim || true
	kubectl delete namespace victim --ignore-not-found

.PHONY: victim-smoke
victim-smoke: check-prereqs
	./scripts/smoke-test.sh

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

.PHONY: generate-fixtures
generate-fixtures: check-prereqs
	./scripts/generate-alert-fixtures.sh
