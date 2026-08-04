from __future__ import annotations

from datetime import datetime
from typing import Any

from seagull_mcp.auth import (
    ConnectorTokenRecord,
    ConnectorTokenStore,
    datetime_from_string,
    datetime_to_string,
)


class DynamoDbConnectorTokenStore(ConnectorTokenStore):
    def __init__(self, table: Any) -> None:
        self._table = table

    def put_token(self, record: ConnectorTokenRecord) -> None:
        self._table.put_item(Item=record_to_item(record), ConditionExpression="attribute_not_exists(token_id)")

    def get_token(self, token_id: str) -> ConnectorTokenRecord | None:
        item = self._table.get_item(Key={"token_id": token_id}).get("Item")
        if item is None:
            return None
        return item_to_record(item)

    def mark_used(self, token_id: str, used_at: datetime) -> None:
        self._table.update_item(
            Key={"token_id": token_id},
            UpdateExpression="SET last_used_at = :last_used_at",
            ExpressionAttributeValues={":last_used_at": datetime_to_string(used_at)},
        )

    def revoke_token(self, token_id: str, revoked_at: datetime) -> ConnectorTokenRecord | None:
        if self.get_token(token_id) is None:
            return None
        result = self._table.update_item(
            Key={"token_id": token_id},
            UpdateExpression="SET revoked_at = :revoked_at",
            ExpressionAttributeValues={":revoked_at": datetime_to_string(revoked_at)},
            ReturnValues="ALL_NEW",
        )
        attributes = result.get("Attributes")
        if attributes is None:
            return None
        return item_to_record(attributes)

    def list_tokens(self, owner_user_id: str) -> tuple[ConnectorTokenRecord, ...]:
        items = []
        query_kwargs: dict[str, Any] = {
            "IndexName": "owner-created-at-index",
            "KeyConditionExpression": "#owner = :owner",
            "ExpressionAttributeNames": {"#owner": "owner_user_id"},
            "ExpressionAttributeValues": {":owner": owner_user_id},
            "ScanIndexForward": False,
        }
        while True:
            result = self._table.query(**query_kwargs)
            items.extend(result.get("Items", []))
            last_key = result.get("LastEvaluatedKey")
            if not last_key:
                break
            query_kwargs["ExclusiveStartKey"] = last_key

        return tuple(item_to_record(item) for item in items)


def record_to_item(record: ConnectorTokenRecord) -> dict[str, Any]:
    item: dict[str, Any] = {
        "token_id": record.token_id,
        "token_hash": record.token_hash,
        "name": record.name,
        "owner_user_id": record.owner_user_id,
        "scopes": list(record.scopes),
        "agent_handles": list(record.agent_handles),
        "created_at": datetime_to_string(record.created_at),
    }
    if record.expires_at is not None:
        item["expires_at"] = datetime_to_string(record.expires_at)
        item["expires_at_epoch"] = int(record.expires_at.timestamp())
    if record.last_used_at is not None:
        item["last_used_at"] = datetime_to_string(record.last_used_at)
    if record.revoked_at is not None:
        item["revoked_at"] = datetime_to_string(record.revoked_at)
    return item


def item_to_record(item: dict[str, Any]) -> ConnectorTokenRecord:
    return ConnectorTokenRecord(
        token_id=item["token_id"],
        token_hash=item["token_hash"],
        name=item["name"],
        owner_user_id=item["owner_user_id"],
        scopes=tuple(item.get("scopes", [])),
        agent_handles=tuple(item.get("agent_handles", [])),
        created_at=datetime_from_string(item["created_at"]) or datetime_from_string("1970-01-01T00:00:00Z"),
        expires_at=datetime_from_string(item.get("expires_at")),
        last_used_at=datetime_from_string(item.get("last_used_at")),
        revoked_at=datetime_from_string(item.get("revoked_at")),
    )
