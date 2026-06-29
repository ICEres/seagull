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
	PYTHONPATH=packages/protocol/src:packages/policy/src python3 -m unittest discover -s packages/protocol/tests
	PYTHONPATH=packages/protocol/src:packages/policy/src python3 -m unittest discover -s packages/policy/tests

sdk-test:
	PYTHONPATH=packages/sdk/src:apps/message-hub/src:packages/policy/src python3 -m unittest discover -s packages/sdk/tests

safety-gateway-test:
	PYTHONPATH=apps/safety-gateway/src:apps/message-hub/src:packages/policy/src python3 -m unittest discover -s apps/safety-gateway/tests

phase2-test: safety-gateway-test

social-api-test:
	PYTHONPATH=apps/social-api/src:packages/protocol/src python3 -m unittest discover -s apps/social-api/tests

phase3-test: social-api-test

ai-provider-test:
	PYTHONPATH=apps/ai-provider/src python3 -m unittest discover -s apps/ai-provider/tests

web-test:
	CI=true pnpm --filter web test

web-build:
	CI=true pnpm --filter web build

phase4-test: web-test web-build

message-hub-test:
	PYTHONPATH=apps/message-hub/src:packages/policy/src python3 -m unittest discover -s apps/message-hub/tests

mcp-connector-test:
	PYTHONPATH=apps/mcp-connector/src python3 -m unittest discover -s apps/mcp-connector/tests

local-agent-test:
	cd connectors/local-agent && GOCACHE="$${TMPDIR:-/tmp}/seagull-go-build" go test ./...

local-agent-go-test: local-agent-test

message-router-test:
	cd apps/message-hub/router && GOCACHE="$${TMPDIR:-/tmp}/seagull-go-build" go test ./...

safety-gateway-build:
	./scripts/build-safety-gateway.sh

social-api-build:
	./scripts/build-social-api.sh

ai-provider-build:
	./scripts/build-ai-provider.sh

mcp-connector-build:
	./scripts/build-mcp-connector.sh

local-agent-build:
	mkdir -p connectors/local-agent/bin
	cd connectors/local-agent && GOCACHE="$${TMPDIR:-/tmp}/seagull-go-build" go build -o bin/seagull ./cmd/seagull

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
	./scripts/smoke-router-ws.mjs "$$(terraform -chdir=infra/terraform/envs/dev output -raw message_router_websocket_url)"

aws-dev-destroy:
	terraform -chdir=infra/terraform/envs/dev destroy

domain-init:
	terraform -chdir=infra/terraform/envs/domain init

domain-plan:
	terraform -chdir=infra/terraform/envs/domain plan

domain-apply:
	terraform -chdir=infra/terraform/envs/domain apply

domain-output:
	terraform -chdir=infra/terraform/envs/domain output

domain-destroy:
	terraform -chdir=infra/terraform/envs/domain destroy
