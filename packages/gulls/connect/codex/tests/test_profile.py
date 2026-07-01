from __future__ import annotations

from unittest import TestCase

from codex_connector import (
    CODEX_AGENT_ALLOWED_USE_TERMS,
    CODEX_AGENT_APPROVAL_REQUIRED_FOR,
    CODEX_AGENT_CAPABILITIES,
    codex_agent_profile,
    codex_agent_profile_body,
)
from seagull_protocol import AgentProfile
from social_api.api import LocalSocialApi


class CodexProfileTest(TestCase):
    def test_codex_profile_maps_to_standard_protocol_profile(self) -> None:
        profile = codex_agent_profile(
            "@Codex:Seagull.Local",
            owner_user_id="user_1",
            node_id="node_1",
        )

        self.assertIsInstance(profile, AgentProfile)
        self.assertEqual("@codex:seagull.local", str(profile.handle))
        self.assertEqual("Codex", profile.display_name)
        self.assertEqual("needs_approval", profile.relationship_posture)
        self.assertEqual(CODEX_AGENT_CAPABILITIES, profile.capabilities)
        self.assertEqual(CODEX_AGENT_APPROVAL_REQUIRED_FOR, profile.approval_required_for)
        self.assertEqual(CODEX_AGENT_ALLOWED_USE_TERMS, profile.allowed_use_terms)
        self.assertEqual(("seagull",), profile.protocols)
        self.assertEqual(("work.v1",), profile.supported_extension_namespaces)
        self.assertEqual("user_1", profile.owner_user_id)
        self.assertEqual("node_1", profile.node_id)
        self.assertFalse(hasattr(profile, "private_prompt"))
        self.assertFalse(hasattr(profile, "tool_credentials"))
        self.assertFalse(hasattr(profile, "mcp_server_url"))

    def test_codex_profile_body_creates_social_profile(self) -> None:
        api = LocalSocialApi.in_memory()
        identity = api.identify_human({"provider": "local", "subject": "alice"})["identity"]
        node = api.create_node({"owner_user_id": identity["user_id"]})["node"]
        token = api.create_pair_token(
            node["node_id"],
            {"owner_user_id": identity["user_id"]},
        )["pair_token"]
        body = codex_agent_profile_body(
            "@codex:seagull.local",
            delivery_mode="pull_webhook",
        )
        body["pair_token"] = token["pair_token"]

        profile = api.register_agent(body)["profile"]

        self.assertEqual("@codex:seagull.local", profile["handle"])
        self.assertEqual("Codex", profile["display_name"])
        self.assertEqual(node["node_id"], profile["node_id"])
        self.assertEqual("needs_approval", profile["relationship_posture"])
        self.assertEqual(list(CODEX_AGENT_CAPABILITIES), profile["capabilities"])
        self.assertEqual(list(CODEX_AGENT_APPROVAL_REQUIRED_FOR), profile["approval_required_for"])
        self.assertEqual(list(CODEX_AGENT_ALLOWED_USE_TERMS), profile["allowed_use_terms"])
        self.assertEqual(["seagull"], profile["protocols"])
        self.assertEqual("pull_webhook", profile["delivery_mode"])
        self.assertIn("personal_agent_api:reply", profile["capabilities"])
        self.assertIn("personal_agent_api:ask_owner", profile["capabilities"])
        self.assertIn("personal_agent_api:request_task", profile["capabilities"])
        self.assertIn("personal_agent_api:return_result", profile["capabilities"])
        self.assertIn("private prompts", profile["contact_explanation"])
        self.assertNotIn("private_prompt", profile)
        self.assertNotIn("tool_credentials", profile)
        self.assertNotIn("mcp_server_url", profile)
