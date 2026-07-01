from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from unittest import TestCase


class FakeKey:
    def __init__(self, name: str) -> None:
        self.name = name

    def eq(self, value: object) -> tuple[str, str, object]:
        return ("eq", self.name, value)


fake_dynamodb = types.ModuleType("boto3.dynamodb")
fake_conditions = types.ModuleType("boto3.dynamodb.conditions")
fake_conditions.Key = FakeKey
sys.modules.setdefault("boto3", types.ModuleType("boto3"))
sys.modules.setdefault("boto3.dynamodb", fake_dynamodb)
sys.modules.setdefault("boto3.dynamodb.conditions", fake_conditions)

from ai_provider.domain.models import (
    ServerCreditLedgerEntry,
    ServerCreditLedgerEntryType,
    UserCreditLedgerEntry,
    UserCreditLedgerEntryType,
)
from ai_provider.storage.dynamodb import DynamoDbAiProviderRepository
from ai_provider.storage.repository import InsufficientCreditBalanceError


class FakeConditionalError(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    def __init__(self, name: str) -> None:
        self.name = name
        self.items: dict[str, dict[str, object]] = {}

    def put_item(self, *, Item: dict[str, object], ConditionExpression: str | None = None) -> None:
        entry_id = str(Item["entry_id"])
        if ConditionExpression == "attribute_not_exists(entry_id)" and entry_id in self.items:
            raise FakeConditionalError()
        self.items[entry_id] = dict(Item)

    def update_item(
        self,
        *,
        Key: dict[str, object],
        UpdateExpression: str,
        ExpressionAttributeValues: dict[str, object],
        ConditionExpression: str | None = None,
    ) -> None:
        entry_id = str(Key["entry_id"])
        current = self.items.get(entry_id)
        available = int((current or {}).get("available_credits", 0))
        if ConditionExpression == "available_credits >= :minimum_available_balance":
            minimum = int(ExpressionAttributeValues[":minimum_available_balance"])
            if available < minimum:
                raise FakeConditionalError()
        item = self.items.setdefault(entry_id, dict(Key))
        if UpdateExpression == "ADD available_credits :delta":
            item["available_credits"] = available + int(ExpressionAttributeValues[":delta"])

    def get_item(self, *, Key: dict[str, object]) -> dict[str, object]:
        return {"Item": self.items.get(str(Key["entry_id"]))}

    def scan(self) -> dict[str, object]:
        return {"Items": list(self.items.values())}

    def query(self, **kwargs: object) -> dict[str, object]:
        expression = kwargs.get("KeyConditionExpression")
        if not (isinstance(expression, tuple) and len(expression) == 3 and expression[0] == "eq"):
            return {"Items": list(self.items.values())}
        _, field_name, expected = expression
        return {"Items": [item for item in self.items.values() if item.get(field_name) == expected]}


class DynamoDbAiProviderRepositoryTest(TestCase):
    def setUp(self) -> None:
        self.tables = {
            "runs": FakeTable("runs"),
            "run_events": FakeTable("run_events"),
            "usage": FakeTable("usage"),
            "user_credit_ledger": FakeTable("user_credit_ledger"),
            "server_credit_ledger": FakeTable("server_credit_ledger"),
            "provider_configs": FakeTable("provider_configs"),
            "admin_audit_events": FakeTable("admin_audit_events"),
            "model_policies": FakeTable("model_policies"),
            "budget_limits": FakeTable("budget_limits"),
        }
        self.repository = DynamoDbAiProviderRepository(
            runs_table=self.tables["runs"],
            run_events_table=self.tables["run_events"],
            usage_table=self.tables["usage"],
            user_credit_ledger_table=self.tables["user_credit_ledger"],
            server_credit_ledger_table=self.tables["server_credit_ledger"],
            provider_configs_table=self.tables["provider_configs"],
            admin_audit_events_table=self.tables["admin_audit_events"],
            model_policies_table=self.tables["model_policies"],
            budget_limits_table=self.tables["budget_limits"],
        )
        self.now = datetime(2026, 6, 30, tzinfo=timezone.utc)

    def test_server_credit_grant_updates_balance_and_ledger(self) -> None:
        entry = ServerCreditLedgerEntry(
            entry_id="server_credit_1",
            entry_type=ServerCreditLedgerEntryType.CREDIT_GRANT,
            credit_delta=100,
            reason="seed",
            admin_actor_id="admin_1",
            created_at=self.now,
        )

        self.repository.append_server_credit_ledger_entry(entry)

        self.assertEqual(100, self.repository.get_server_credit_balance())
        self.assertEqual((entry,), self.repository.list_server_credit_ledger())

    def test_transfer_server_credits_updates_server_and_user_balances(self) -> None:
        grant = ServerCreditLedgerEntry(
            entry_id="server_credit_1",
            entry_type=ServerCreditLedgerEntryType.CREDIT_GRANT,
            credit_delta=100,
            reason="seed",
            admin_actor_id="admin_1",
            created_at=self.now,
        )
        server_entry = ServerCreditLedgerEntry(
            entry_id="server_credit_2",
            entry_type=ServerCreditLedgerEntryType.USER_CREDIT_GRANT,
            credit_delta=-40,
            reason="grant user",
            admin_actor_id="admin_1",
            owner_user_id="owner_1",
            user_credit_entry_id="user_credit_1",
            created_at=self.now,
        )
        user_entry = UserCreditLedgerEntry(
            entry_id="user_credit_1",
            owner_user_id="owner_1",
            entry_type=UserCreditLedgerEntryType.CREDIT_GRANT,
            credit_delta=40,
            reason="grant user",
            created_at=self.now,
        )

        self.repository.append_server_credit_ledger_entry(grant)
        self.repository.transfer_server_credits_to_user(
            user_entry,
            server_entry,
            minimum_server_available_balance=40,
        )

        self.assertEqual(60, self.repository.get_server_credit_balance())
        self.assertEqual(40, self.repository.get_user_credit_balance("owner_1"))

    def test_transfer_server_credits_rejects_insufficient_balance(self) -> None:
        server_entry = ServerCreditLedgerEntry(
            entry_id="server_credit_1",
            entry_type=ServerCreditLedgerEntryType.USER_CREDIT_GRANT,
            credit_delta=-40,
            reason="grant user",
            admin_actor_id="admin_1",
            owner_user_id="owner_1",
            user_credit_entry_id="user_credit_1",
            created_at=self.now,
        )
        user_entry = UserCreditLedgerEntry(
            entry_id="user_credit_1",
            owner_user_id="owner_1",
            entry_type=UserCreditLedgerEntryType.CREDIT_GRANT,
            credit_delta=40,
            reason="grant user",
            created_at=self.now,
        )

        with self.assertRaises(InsufficientCreditBalanceError):
            self.repository.transfer_server_credits_to_user(
                user_entry,
                server_entry,
                minimum_server_available_balance=40,
            )

        self.assertEqual(0, self.repository.get_server_credit_balance())
        self.assertEqual(0, self.repository.get_user_credit_balance("owner_1"))
