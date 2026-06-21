from __future__ import annotations

import base64
import os
from typing import Any

import boto3

from seagull_mcp.client import SeagullHttpClient
from seagull_mcp.cognito import CognitoJwtVerifier, CognitoPrincipalResolver
from seagull_mcp.oauth_proxy import CognitoOAuthProxy
from seagull_mcp.server import McpConnectorApp, response_to_lambda
from seagull_mcp.storage import DynamoDbConnectorTokenStore


def bool_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def csv_env(name: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.environ.get(name, "").split(",") if value.strip())


CognitoConfig = tuple[str, str, str]


def cognito_config() -> CognitoConfig | None:
    user_pool_id = os.environ.get("MCP_COGNITO_USER_POOL_ID")
    client_id = os.environ.get("MCP_COGNITO_CLIENT_ID")
    region = os.environ.get("MCP_COGNITO_REGION")
    if not user_pool_id or not client_id or not region:
        return None
    return user_pool_id, client_id, region


dynamodb = boto3.resource("dynamodb")
token_store = DynamoDbConnectorTokenStore(dynamodb.Table(os.environ["CONNECTOR_TOKENS_TABLE"]))
client = SeagullHttpClient(message_api_url=os.environ["MESSAGE_API_URL"])
cognito = cognito_config()
cognito_resolver = None
oauth_proxy = None
if cognito is not None:
    user_pool_id, client_id, region = cognito
    cognito_resolver = CognitoPrincipalResolver(
        verifier=CognitoJwtVerifier(user_pool_id=user_pool_id, app_client_id=client_id, region=region),
        user_pool_id=user_pool_id,
        identity_provider=boto3.client("cognito-idp", region_name=region),
    )
    authorization_url = os.environ.get("MCP_COGNITO_AUTHORIZATION_URL")
    token_url = os.environ.get("MCP_COGNITO_TOKEN_URL")
    if authorization_url and token_url:
        oauth_proxy = CognitoOAuthProxy(
            authorization_url=authorization_url,
            token_url=token_url,
            client_id=client_id,
        )
app = McpConnectorApp(
    token_store=token_store,
    seagull_client=client,
    resource_uri=os.environ.get("MCP_RESOURCE_URI", "https://mcp.gulls.ai/mcp"),
    authorization_server=os.environ.get("MCP_AUTHORIZATION_SERVER") or None,
    dev_token=os.environ.get("MCP_DEV_TOKEN") or None,
    dev_owner_user_id=os.environ.get("MCP_DEV_OWNER_USER_ID", "user_dev"),
    dev_agent_handles=csv_env("MCP_DEV_AGENT_HANDLES"),
    no_auth_enabled=bool_env("MCP_NO_AUTH_ENABLED"),
    no_auth_owner_user_id=os.environ.get("MCP_NO_AUTH_OWNER_USER_ID", "user_chatgpt_dev"),
    no_auth_agent_handles=csv_env("MCP_NO_AUTH_AGENT_HANDLES"),
    no_auth_scopes=csv_env("MCP_NO_AUTH_SCOPES") or ("agents:read",),
    cognito_resolver=cognito_resolver,
    oauth_proxy=oauth_proxy,
    admin_secret=os.environ.get("CONNECTOR_TOKEN_ADMIN_SECRET") or None,
)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath") or event.get("requestContext", {}).get("http", {}).get("path", "/")
    headers = event.get("headers") or {}
    query = event.get("queryStringParameters") or {}
    body = event.get("body")
    if body is not None and event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    return response_to_lambda(app.handle(method=method, path=path, headers=headers, body=body, query=query))
