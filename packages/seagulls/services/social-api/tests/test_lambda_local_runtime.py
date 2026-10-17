from __future__ import annotations

import os
from typing import Any
from unittest import TestCase
from unittest.mock import patch

from social_api.domain import SocialApiService
from social_api.storage import InMemorySocialRepository

from test_lambda_auth import event, load_lambda_module, response_body


class FakeMessageHubRuntimeClient:
    issued: list[dict[str, str]] = []
    revoked: list[str] = []
    principal_value: dict[str, str] | None = None

    @classmethod
    def reset(cls) -> None:
        cls.issued = []
        cls.revoked = []
        cls.principal_value = None

    def issue_token(self, *, handle: str, owner_user_id: str, node_id: str) -> dict[str, Any]:
        token_id = f"token_{len(type(self).issued) + 1}"
        record = {
            "token_id": token_id,
            "agent_handle": handle,
            "owner_user_id": owner_user_id,
            "node_id": node_id,
        }
        type(self).issued.append(record)
        return {"token": f"sga_runtime_{len(type(self).issued)}", "record": record}

    def revoke_token(self, token_id: str) -> None:
        type(self).revoked.append(token_id)

    def principal(self, request: dict[str, Any]) -> dict[str, str]:
        authorization = {str(k).lower(): str(v) for k, v in (request.get("headers") or {}).items()}.get(
            "authorization", ""
        )
        if authorization != "Bearer sga_runtime_1":
            raise AssertionError("heartbeat did not forward the runtime Bearer token")
        principal = type(self).principal_value
        if principal is None:
            raise AssertionError("heartbeat principal was not configured")
        return principal


class SocialApiLambdaLocalRuntimeTest(TestCase):
    OWNER_CLAIMS = {"sub": "alice-sub", "email": "alice@example.com"}
    OTHER_CLAIMS = {"sub": "bob-sub", "email": "bob@example.com"}
    HANDLE = "@codex:gulls.ai"
    ENV = {
        "MESSAGE_API_URL": "https://hub.test",
        "SOCIAL_PUBLIC_API_URL": "https://api.gulls.ai",
    }

    def setUp(self) -> None:
        FakeMessageHubRuntimeClient.reset()
        self.env_patcher = patch.dict(os.environ, self.ENV)
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        self.lambda_module = load_lambda_module()
        self.lambda_module.service = SocialApiService(InMemorySocialRepository())
        identity = self.lambda_module.service.identify_human(
            provider="cognito",
            subject=self.OWNER_CLAIMS["sub"],
            email=self.OWNER_CLAIMS["email"],
        )
        self.owner_id = identity.user_id
        self.lambda_module.service.create_agent_profile(
            owner_user_id=self.owner_id,
            handle=self.HANDLE,
        )

    def invoke(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.lambda_module.handler(event(method, path, **kwargs), None)

    def test_runtime_mode_requires_authentication_and_owner(self) -> None:
        path = "/profiles/%40codex%3Agulls.ai/runtime"

        unauthenticated = self.invoke("PUT", path, body={"mode": "local"})
        self.assertEqual(401, unauthenticated["statusCode"])

        non_owner = self.invoke(
            "PUT",
            path,
            body={"mode": "local"},
            claims=self.OTHER_CLAIMS,
        )
        self.assertEqual(403, non_owner["statusCode"])

        owner = self.invoke("PUT", path, body={"mode": "local"}, claims=self.OWNER_CLAIMS)
        self.assertEqual(200, owner["statusCode"])
        self.assertEqual("local", response_body(owner)["runtime"]["mode"])

        fetched = self.invoke("GET", path, claims=self.OWNER_CLAIMS)
        self.assertEqual(200, fetched["statusCode"])
        self.assertEqual("local", response_body(fetched)["runtime"]["mode"])

    def test_pair_token_generation_requires_authentication_and_owner(self) -> None:
        path = "/profiles/%40codex%3Agulls.ai/local-pair-tokens"

        unauthenticated = self.invoke("POST", path)
        self.assertEqual(401, unauthenticated["statusCode"])

        non_owner = self.invoke("POST", path, claims=self.OTHER_CLAIMS)
        self.assertEqual(403, non_owner["statusCode"])

        owner = self.invoke("POST", path, claims=self.OWNER_CLAIMS)
        self.assertEqual(200, owner["statusCode"])
        self.assertTrue(response_body(owner)["pair_token"]["pair_token"])

    def test_pair_exchange_returns_runtime_credentials_and_rejects_replay(self) -> None:
        token_response = self.invoke(
            "POST",
            "/profiles/%40codex%3Agulls.ai/local-pair-tokens",
            claims=self.OWNER_CLAIMS,
        )
        pair_token = response_body(token_response)["pair_token"]["pair_token"]

        with patch.dict(os.environ, self.ENV), patch.object(
            self.lambda_module, "MessageHubRuntimeClient", FakeMessageHubRuntimeClient
        ):
            paired = self.invoke("POST", "/local-connections/pair", body={"pair_token": pair_token})
            replay = self.invoke("POST", "/local-connections/pair", body={"pair_token": pair_token})

        self.assertEqual(200, paired["statusCode"])
        body = response_body(paired)
        self.assertEqual("https://hub.test", body["api_url"])
        self.assertEqual("https://api.gulls.ai", body["social_api_url"])
        self.assertEqual(self.HANDLE, body["agent_handle"])
        self.assertTrue(body["node_id"])
        self.assertEqual("sga_runtime_1", body["token"])
        self.assertEqual("token_1", body["token_id"])
        self.assertEqual(400, replay["statusCode"])
        self.assertEqual(1, len(FakeMessageHubRuntimeClient.issued))

    def test_heartbeat_uses_bearer_token_and_updates_bound_runtime(self) -> None:
        self.lambda_module.service.set_agent_prompt(
            owner_user_id=self.owner_id,
            agent_handle=self.HANDLE,
            instructions="Answer briefly and ask before taking external actions.",
        )
        token_response = self.invoke(
            "POST",
            "/profiles/%40codex%3Agulls.ai/local-pair-tokens",
            claims=self.OWNER_CLAIMS,
        )
        pair_token = response_body(token_response)["pair_token"]["pair_token"]

        with patch.dict(os.environ, self.ENV), patch.object(
            self.lambda_module, "MessageHubRuntimeClient", FakeMessageHubRuntimeClient
        ):
            paired = self.invoke("POST", "/local-connections/pair", body={"pair_token": pair_token})
            paired_body = response_body(paired)
            FakeMessageHubRuntimeClient.principal_value = {
                "owner_user_id": self.owner_id,
                "agent_handle": self.HANDLE,
                "node_id": paired_body["node_id"],
                "token_id": paired_body["token_id"],
            }
            heartbeat = self.invoke(
                "POST",
                "/local-connections/heartbeat",
                headers={"Authorization": "Bearer sga_runtime_1"},
            )

        self.assertEqual(200, heartbeat["statusCode"])
        self.assertEqual(
            {
                "connected": True,
                "local_runtime": {
                    "agent_handle": self.HANDLE,
                    "mode": "cloud",
                    "instructions": "Answer briefly and ask before taking external actions.",
                },
            },
            response_body(heartbeat),
        )
        runtime = self.lambda_module.service.get_agent_runtime(
            owner_user_id=self.owner_id,
            agent_handle=self.HANDLE,
        )
        self.assertTrue(runtime["connected"])
        self.assertEqual(paired_body["node_id"], runtime["node_id"])
        self.assertIsNotNone(runtime["last_seen_at"])

    def test_heartbeat_does_not_expose_prompt_for_replaced_or_non_node_principal(self) -> None:
        self.lambda_module.service.set_agent_prompt(
            owner_user_id=self.owner_id,
            agent_handle=self.HANDLE,
            instructions="Private owner instructions.",
        )
        token_response = self.invoke(
            "POST",
            "/profiles/%40codex%3Agulls.ai/local-pair-tokens",
            claims=self.OWNER_CLAIMS,
        )
        pair_token = response_body(token_response)["pair_token"]["pair_token"]

        with patch.dict(os.environ, self.ENV), patch.object(
            self.lambda_module, "MessageHubRuntimeClient", FakeMessageHubRuntimeClient
        ):
            paired = self.invoke("POST", "/local-connections/pair", body={"pair_token": pair_token})
            paired_body = response_body(paired)
            for principal in (
                {
                    "owner_user_id": self.owner_id,
                    "agent_handle": self.HANDLE,
                    "node_id": paired_body["node_id"],
                    "token_id": "replaced-token",
                },
                {
                    "owner_user_id": self.owner_id,
                    "agent_handle": self.HANDLE,
                    "node_id": None,
                    "token_id": paired_body["token_id"],
                },
            ):
                FakeMessageHubRuntimeClient.principal_value = principal
                rejected = self.invoke(
                    "POST",
                    "/local-connections/heartbeat",
                    headers={"Authorization": "Bearer sga_runtime_1"},
                )
                self.assertEqual(403, rejected["statusCode"])
                self.assertNotIn("Private owner instructions.", str(response_body(rejected)))

    def test_disconnect_requires_authentication_and_owner_and_revokes_token(self) -> None:
        token_response = self.invoke(
            "POST",
            "/profiles/%40codex%3Agulls.ai/local-pair-tokens",
            claims=self.OWNER_CLAIMS,
        )
        pair_token = response_body(token_response)["pair_token"]["pair_token"]

        with patch.dict(os.environ, self.ENV), patch.object(
            self.lambda_module, "MessageHubRuntimeClient", FakeMessageHubRuntimeClient
        ):
            self.invoke("POST", "/local-connections/pair", body={"pair_token": pair_token})
            path = "/profiles/%40codex%3Agulls.ai/local-connection"
            unauthenticated = self.invoke("DELETE", path)
            non_owner = self.invoke("DELETE", path, claims=self.OTHER_CLAIMS)
            disconnected = self.invoke("DELETE", path, claims=self.OWNER_CLAIMS)

        self.assertEqual(401, unauthenticated["statusCode"])
        self.assertEqual(403, non_owner["statusCode"])
        self.assertEqual(200, disconnected["statusCode"])
        self.assertEqual("cloud", response_body(disconnected)["runtime"]["mode"])
        self.assertEqual(["token_1"], FakeMessageHubRuntimeClient.revoked)
