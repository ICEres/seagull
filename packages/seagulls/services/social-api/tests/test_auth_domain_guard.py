from __future__ import annotations

import importlib.util
import types
from pathlib import Path
from unittest import TestCase


def load_guard() -> types.ModuleType:
    path = Path(__file__).resolve().parents[1] / "aws" / "auth_domain_guard.py"
    spec = importlib.util.spec_from_file_location("_auth_domain_guard_for_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load auth domain guard")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def auth_event(email: str | None, *, username: str = "user") -> dict[str, object]:
    attributes = {} if email is None else {"email": email}
    return {
        "triggerSource": "PreSignUp_SignUp",
        "userName": username,
        "request": {"userAttributes": attributes},
        "response": {},
    }


class AuthDomainGuardTest(TestCase):
    def setUp(self) -> None:
        self.guard = load_guard()

    def test_allows_exact_domain_case_insensitively(self) -> None:
        event = auth_event("User@EXAMPLE.TEST")

        self.assertIs(event, self.guard.handler(event, None))

    def test_rejects_other_and_subdomains(self) -> None:
        for email in ("user@example.com", "user@team.example.test"):
            with self.subTest(email=email), self.assertRaisesRegex(
                ValueError,
                r"Only @aiisu\.com email addresses are allowed\.",
            ):
                self.guard.handler(auth_event(email), None)

    def test_rejects_missing_email(self) -> None:
        with self.assertRaisesRegex(ValueError, r"Only @aiisu\.com"):
            self.guard.handler(auth_event(None), None)

    def test_accepts_email_username_when_attributes_are_unavailable(self) -> None:
        event = auth_event(None, username="user@example.test")

        self.assertIs(event, self.guard.handler(event, None))
