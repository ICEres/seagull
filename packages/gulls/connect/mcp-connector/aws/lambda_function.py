from __future__ import annotations

import base64
import json
import os
from typing import Any

import boto3

from seagull_common.lambda_runtime import csv_env
from seagull_mcp.client import SeagullHttpClient
from seagull_mcp.cognito import CognitoJwtVerifier, CognitoPrincipalResolver
from seagull_mcp.oauth_proxy import CognitoOAuthProxy
from seagull_mcp.server import McpConnectorApp, response_to_lambda
from seagull_mcp.storage import DynamoDbConnectorTokenStore


def bool_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def secret_env(name: str) -> str | None:
    direct = os.environ.get(name, "").strip()
    secret_arn = os.environ.get(f"{name}_ARN", "").strip()
    if direct:
        return direct
    if not secret_arn:
        return None
    try:
        result = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
    except Exception as exc:
        print(json.dumps({"level": "warning", "message": f"could not load secret {name}: {exc}"}))
        return None
    secret = result.get("SecretString")
    if isinstance(secret, str):
        stripped = secret.strip()
        return stripped or None
    encoded = result.get("SecretBinary")
    if isinstance(encoded, (bytes, bytearray)):
        stripped = base64.b64decode(encoded).decode("utf-8").strip()
        return stripped or None
    if isinstance(encoded, str):
        stripped = base64.b64decode(encoded).decode("utf-8").strip()
        return stripped or None
    return None


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
    dev_token=secret_env("MCP_DEV_TOKEN"),
    dev_owner_user_id=os.environ.get("MCP_DEV_OWNER_USER_ID", "user_dev"),
    dev_agent_handles=csv_env("MCP_DEV_AGENT_HANDLES"),
    no_auth_enabled=bool_env("MCP_NO_AUTH_ENABLED"),
    no_auth_owner_user_id=os.environ.get("MCP_NO_AUTH_OWNER_USER_ID", "user_chatgpt_dev"),
    no_auth_agent_handles=csv_env("MCP_NO_AUTH_AGENT_HANDLES"),
    no_auth_scopes=csv_env("MCP_NO_AUTH_SCOPES") or ("agents:read",),
    cognito_resolver=cognito_resolver,
    oauth_proxy=oauth_proxy,
    admin_secret=secret_env("CONNECTOR_TOKEN_ADMIN_SECRET"),
)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath") or event.get("requestContext", {}).get("http", {}).get("path", "/")
    headers = event.get("headers") or {}
    query = event.get("queryStringParameters") or {}
    body = event.get("body")
    if body is not None and event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    origin = headers.get("origin") or headers.get("Origin")
    return response_to_lambda(
        app.handle(method=method, path=path, headers=headers, body=body, query=query),
        request_origin=origin,
        allowed_origins=csv_env("MCP_CORS_ALLOWED_ORIGINS") or ("https://chatgpt.com", "https://chat.openai.com"),
    )
