.PHONY: setup local-up local-down local-logs local-clean check-local-env phase0-test sdk-test safety-gateway-test phase2-test social-api-test phase3-test ai-provider-test web-test web-build phase4-test message-hub-test mcp-connector-test local-agent-test local-agent-go-test message-router-test safety-gateway-build social-api-build ai-provider-build mcp-connector-build local-agent-build message-router-build aws-dev-init aws-dev-plan aws-dev-apply aws-dev-output aws-dev-smoke aws-dev-safety-smoke aws-dev-ai-smoke aws-dev-social-smoke aws-dev-web-smoke aws-dev-router-smoke aws-dev-destroy domain-init domain-plan domain-apply domain-output domain-destroy

setup:
	./scripts/setup-local.sh

local-up:
	docker compose -f infra/local/docker-compose.yml up -d dynamodb-local

local-down:
	docker compose -f infra/local/docker-compose.yml down

local-logs:
	docker compose -f infra/local/docker-compose.yml logs -f

local-clean:
	docker compose -f infra/local/docker-compose.yml down -v

check-local-env:
	./scripts/check-local-env.sh

phase0-test:
	PYTHONPATH=packages/gulls/packages/protocol/src:packages/gulls/packages/policy/src python3 -m unittest discover -s packages/gulls/packages/protocol/tests
	PYTHONPATH=packages/gulls/packages/protocol/src:packages/gulls/packages/policy/src python3 -m unittest discover -s packages/gulls/packages/policy/tests

sdk-test:
	PYTHONPATH=packages/gulls/packages/sdk/src:packages/gulls/services/message-hub/src:packages/gulls/packages/policy/src python3 -m unittest discover -s packages/gulls/packages/sdk/tests

safety-gateway-test:
	PYTHONPATH=packages/gulls/services/safety-gateway/src:packages/gulls/services/message-hub/src:packages/gulls/packages/policy/src python3 -m unittest discover -s packages/gulls/services/safety-gateway/tests

phase2-test: safety-gateway-test

social-api-test:
	PYTHONPATH=packages/seagulls/services/social-api/src:packages/gulls/packages/protocol/src python3 -m unittest discover -s packages/seagulls/services/social-api/tests

phase3-test: social-api-test

ai-provider-test:
	PYTHONPATH=packages/gulls/services/ai-provider/src python3 -m unittest discover -s packages/gulls/services/ai-provider/tests

web-test:
	CI=true pnpm --filter web test

web-build:
	CI=true pnpm --filter web build

phase4-test: web-test web-build

message-hub-test:
	PYTHONPATH=packages/gulls/services/message-hub/src:packages/gulls/packages/policy/src python3 -m unittest discover -s packages/gulls/services/message-hub/tests

mcp-connector-test:
	PYTHONPATH=packages/gulls/connect/mcp-connector/src python3 -m unittest discover -s packages/gulls/connect/mcp-connector/tests

local-agent-test:
	cd packages/gulls/connect/local-agent && GOCACHE="$${TMPDIR:-/tmp}/seagull-go-build" go test ./...

local-agent-go-test: local-agent-test

message-router-test:
	cd packages/gulls/services/message-hub/router && GOCACHE="$${TMPDIR:-/tmp}/seagull-go-build" go test ./...

safety-gateway-build:
	./scripts/build-safety-gateway.sh

social-api-build:
	./scripts/build-social-api.sh

ai-provider-build:
	./scripts/build-ai-provider.sh

mcp-connector-build:
	./scripts/build-mcp-connector.sh

local-agent-build:
	mkdir -p packages/gulls/connect/local-agent/bin
	cd packages/gulls/connect/local-agent && GOCACHE="$${TMPDIR:-/tmp}/seagull-go-build" go build -o bin/gulls ./cmd/gulls
	cd packages/gulls/connect/local-agent && GOCACHE="$${TMPDIR:-/tmp}/seagull-go-build" go build -o bin/seagull ./cmd/seagull

message-router-build:
	./scripts/build-message-router.sh

aws-dev-init:
	@if [ -f infra/terraform/envs/dev/backend.hcl ]; then \
		terraform -chdir=infra/terraform/envs/dev init -backend-config=backend.hcl; \
	else \
		terraform -chdir=infra/terraform/envs/dev init -backend=false; \
	fi

aws-dev-plan: safety-gateway-build social-api-build ai-provider-build mcp-connector-build message-router-build web-build
	terraform -chdir=infra/terraform/envs/dev plan

aws-dev-apply: safety-gateway-build social-api-build ai-provider-build mcp-connector-build message-router-build web-build
	terraform -chdir=infra/terraform/envs/dev apply

aws-dev-output:
	terraform -chdir=infra/terraform/envs/dev output

aws-dev-smoke:
	./scripts/smoke-aws-dev.sh

aws-dev-safety-smoke:
	./scripts/smoke-safety-gateway.sh

aws-dev-ai-smoke:
	./scripts/smoke-ai-provider.sh

aws-dev-social-smoke:
	./scripts/smoke-social-api.sh

aws-dev-web-smoke:
	./scripts/smoke-web.sh

aws-dev-router-smoke:
	./scripts/smoke-router-ws.mjs "$$(terraform -chdir=infra/terraform/envs/dev output -raw message_router_websocket_url)" "$$(terraform -chdir=infra/terraform/envs/dev output -raw message_api_url)"

aws-dev-destroy:
	terraform -chdir=infra/terraform/envs/dev destroy

domain-init:
	@if [ -f infra/terraform/envs/domain/backend.hcl ]; then \
		terraform -chdir=infra/terraform/envs/domain init -backend-config=backend.hcl; \
	else \
		echo "infra/terraform/envs/domain/backend.hcl is required for remote state"; \
		exit 1; \
	fi

domain-plan:
	terraform -chdir=infra/terraform/envs/domain plan

domain-apply:
	terraform -chdir=infra/terraform/envs/domain apply

domain-output:
	terraform -chdir=infra/terraform/envs/domain output

domain-destroy:
	terraform -chdir=infra/terraform/envs/domain destroy
