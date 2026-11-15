# Lock files: fully pinned dependency trees generated from requirements/*.in.
# dev.txt is cross-platform (your Mac and CI); app.txt and ai.txt are resolved for
# the images: Linux arm64, Python 3.12. Constrained by dev.txt so shared packages
# get the same versions everywhere.
LOCK = uv pip compile --quiet --python-version 3.12 $(LOCK_ARGS)
# PyTorch's CPU-only index, for torch==...+cpu (see requirements/ai.in). That index
# also mirrors old copies of common packages (urllib3, setuptools, ...), so uv
# must pick the best version across both indexes, not the first index that has a
# package. Both indexes are first-party; see docs/security.md.
TORCH_CPU = --extra-index-url https://download.pytorch.org/whl/cpu --emit-index-url --index-strategy unsafe-best-match
# Extra flags for one run, e.g. make lock LOCK_ARGS="--upgrade-package torch"
LOCK_ARGS ?=
IMAGE_PLATFORM = --python-platform aarch64-unknown-linux-gnu

.PHONY: up down leftovers status cost lock lint test images push ruleset load load-clean drill grafana trace secrets secrets-check lint-infra lint-chart argocd dev-up dev-down dev-reset dev-logs

# --- Lifecycle -----------------------------------------------------------------
# From nothing to a working URL, and back to zero cost.
up:
	scripts/up.sh

down:
	scripts/down.sh

# Anything from the platform layer still in AWS (also run by `make down` and nightly in CI).
leftovers:
	scripts/leftovers.sh

status:
	scripts/status.sh

cost:
	scripts/cost.sh

lock:
	$(LOCK) $(TORCH_CPU) --universal requirements/dev.in -o requirements/dev.txt
	$(LOCK) --index-strategy unsafe-best-match $(IMAGE_PLATFORM) -c requirements/dev.txt requirements/app.in -o requirements/app.txt
	$(LOCK) $(TORCH_CPU) $(IMAGE_PLATFORM) -c requirements/dev.txt requirements/ai.in -o requirements/ai.txt

lint:
	ruff check .

test:
	python -m pytest -q

# Both images for linux/arm64 (Graviton). No attestations: one manifest per push to
# ECR, which keeps the lifecycle policy safe (infra/bootstrap/ecr.tf).
IMAGE_TAG ?= dev
BUILD = docker buildx build --platform linux/arm64 --provenance=false --sbom=false --load

images:
	$(BUILD) --target app -t vibesense-app:$(IMAGE_TAG) .
	$(BUILD) --target ai -t vibesense-ai:$(IMAGE_TAG) .

# Build and push both images to ECR, tagged with the current commit, then put
# that tag in deploy/charts/vibesense/values.yaml. Merges to main do this
# automatically (.github/workflows/release.yml); this is the manual fallback.
# The tag must describe the code, so it refuses to run with uncommitted changes
# to anything that goes into an image.
REGISTRY = $(shell aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com
GIT_SHA = $(shell git rev-parse --short=12 HEAD)
IMAGE_INPUTS = src requirements Dockerfile alembic alembic.ini .streamlit

push:
	@test -z "$$(git status --porcelain -- $(IMAGE_INPUTS))" || { echo "Commit changes to $(IMAGE_INPUTS) first: the tag must match the code." >&2; exit 1; }
	$(MAKE) images IMAGE_TAG=$(GIT_SHA)
	aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $(REGISTRY)
	for image in app ai; do \
		docker tag vibesense-$$image:$(GIT_SHA) $(REGISTRY)/vibesense-$$image:$(GIT_SHA) && \
		docker push $(REGISTRY)/vibesense-$$image:$(GIT_SHA) || exit 1; \
	done
	@echo "Pushed tag $(GIT_SHA). Set images.app.tag and images.ai.tag to it in deploy/charts/vibesense/values.yaml."

# Terraform checks, the same three CI runs on infra PRs (Task 7.2).
TFLINT = tflint --config "$(CURDIR)/infra/.tflint.hcl"

lint-infra:
	terraform fmt -check -recursive infra
	$(TFLINT) --init
	cd infra && $(TFLINT) --recursive
	checkov --directory infra --framework terraform --compact --quiet

# App secrets in SSM Parameter Store (/vibesense/secrets/*), never via Terraform.
secrets:
	scripts/put-secrets.sh

secrets-check:
	scripts/put-secrets.sh --check

# One job's log lines from every stage, in time order.
#   make trace JOB=<job_id>                     # from the running pods
#   make trace JOB=<job_id> SOURCE=cloudwatch   # from CloudWatch Logs (includes removed pods)
trace:
	scripts/trace-job.sh $(JOB) $(if $(filter cloudwatch,$(SOURCE)),--cloudwatch,)

# Grafana: the admin password, then a port-forward (Ctrl-C to stop).
grafana:
	@echo "Grafana: http://localhost:3000  user: admin  password: $$(kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d)"
	kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80

# Install Argo CD and apply the root app (after `terraform apply` + kubeconfig).
argocd:
	scripts/bootstrap-argocd.sh

# Load test (Phase 8): synthetic jobs at example.com (never emailed) and
# messages straight to the analysis queue, run as a Job in the cluster.
JOBS ?= 20
MESSAGES ?= 200
load:
	scripts/load-test.sh --jobs $(JOBS) --messages $(MESSAGES)

load-clean:
	scripts/load-test.sh --cleanup

# Spot interruption drill: drain a busy burst node mid-load, measure recovery.
drill:
	scripts/drain-drill.sh

# Branch protection for main, from .github/rulesets/main.json.
ruleset:
	scripts/apply-ruleset.sh

# Render the app chart with placeholder values (Argo CD supplies the real ones).
CHART := deploy/charts/vibesense
CHART_TEST_VALUES := --set awsAccountId=123456789012 --set registry=123456789012.dkr.ecr.us-east-1.amazonaws.com \
	--set images.app.tag=test --set images.ai.tag=test --set ingress.allowedCidrs=203.0.113.7/32
lint-chart:
	helm lint $(CHART) $(CHART_TEST_VALUES)
	helm template vibesense $(CHART) -n vibesense $(CHART_TEST_VALUES) > /dev/null

# Local stack (docker-compose.yml): UI on :8501, inbox on :8025.
dev-up:
	docker compose up --build -d
	@echo "UI: http://localhost:8501   Inbox: http://localhost:8025"

dev-down:
	docker compose down

dev-reset:  ## also deletes the local database
	docker compose down -v

dev-logs:
	docker compose logs -f --tail=50 ingestion ai aggregation notification local-scheduler
