from __future__ import annotations

import base64
import io
import json
import os
from contextlib import redirect_stdout
from unittest import TestCase
from unittest.mock import patch

from seagull_common.lambda_runtime import (
    cors_headers,
    cors_response,
    csv_env,
    env_bool,
    env_int,
    jwt_claims,
    parse_body,
    path_param,
    redacted_event,
    response,
    secret_env,
)
from seagull_common.logging import log


class BadRequest(ValueError):
    pass


class EnvHelpersTest(TestCase):
    def test_secret_env_prefers_direct_value(self) -> None:
        with patch.dict(os.environ, {"MY_SECRET": " s3cret ", "MY_SECRET_ARN": "arn:aws:..."}, clear=False):
            self.assertEqual("s3cret", secret_env("MY_SECRET"))

    def test_secret_env_empty_without_value_or_arn(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual("", secret_env("MY_SECRET"))

    def test_csv_env_parses_and_defaults(self) -> None:
        with patch.dict(os.environ, {"NAMES": " a , ,b "}, clear=False):
            self.assertEqual(("a", "b"), csv_env("NAMES"))
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual((), csv_env("NAMES"))
            self.assertEqual(("x",), csv_env("NAMES", ("x",)))

    def test_env_bool(self) -> None:
        with patch.dict(os.environ, {"FLAG": "TRUE"}, clear=False):
            self.assertTrue(env_bool("FLAG", default=False))
        with patch.dict(os.environ, {"FLAG": "nope"}, clear=False):
            self.assertFalse(env_bool("FLAG", default=True))
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(env_bool("FLAG", default=True))

    def test_env_int_applies_default_and_minimum(self) -> None:
        with patch.dict(os.environ, {"LIMIT": "5"}, clear=False):
            self.assertEqual(10, env_int("LIMIT", default=64, minimum=10))
        with patch.dict(os.environ, {"LIMIT": "not-a-number"}, clear=False):
            self.assertEqual(64, env_int("LIMIT", default=64, minimum=10))
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(64, env_int("LIMIT", default=64, minimum=10))


class ParseBodyTest(TestCase):
    def test_missing_body_is_empty_dict(self) -> None:
        self.assertEqual({}, parse_body({}, error=BadRequest))

    def test_parses_json_object(self) -> None:
        event = {"body": json.dumps({"a": 1})}
        self.assertEqual({"a": 1}, parse_body(event, error=BadRequest))

    def test_decodes_base64_body(self) -> None:
        raw = base64.b64encode(json.dumps({"a": 1}).encode("utf-8")).decode("ascii")
        event = {"body": raw, "isBase64Encoded": True}
        self.assertEqual({"a": 1}, parse_body(event, error=BadRequest))

    def test_rejects_invalid_json(self) -> None:
        with self.assertRaises(BadRequest) as ctx:
            parse_body({"body": "{nope"}, error=BadRequest)
        self.assertEqual("body must be valid JSON", str(ctx.exception))

    def test_rejects_non_object_json(self) -> None:
        with self.assertRaises(BadRequest) as ctx:
            parse_body({"body": "[1]"}, error=BadRequest)
        self.assertEqual("body must be a JSON object", str(ctx.exception))


class ResponseShapingTest(TestCase):
    def test_response_is_compact_json_with_content_type(self) -> None:
        result = response(200, {"ok": True})
        self.assertEqual(200, result["statusCode"])
        self.assertEqual({"content-type": "application/json"}, result["headers"])
        self.assertEqual('{"ok":true}', result["body"])

    def test_response_merges_extra_headers(self) -> None:
        headers = cors_headers(allow_headers="authorization,content-type")
        result = response(204, {}, headers=headers)
        self.assertEqual("application/json", result["headers"]["content-type"])
        self.assertEqual("*", result["headers"]["access-control-allow-origin"])

    def test_cors_headers_shape(self) -> None:
        self.assertEqual(
            {
                "access-control-allow-origin": "*",
                "access-control-allow-methods": "GET,POST,OPTIONS",
                "access-control-allow-headers": "authorization,content-type,x-secret",
                "access-control-max-age": "300",
            },
            cors_headers(allow_headers="authorization,content-type,x-secret", max_age=300),
        )

    def test_cors_response_is_empty_204(self) -> None:
        result = cors_response(headers={"access-control-allow-origin": "*"})
        self.assertEqual(204, result["statusCode"])
        self.assertEqual("", result["body"])
        self.assertEqual({"access-control-allow-origin": "*"}, result["headers"])


class EventHelpersTest(TestCase):
    def test_redacted_event_hides_headers_and_body(self) -> None:
        event = {
            "rawPath": "/health",
            "requestContext": {"http": {"method": "GET"}},
            "queryStringParameters": {"a": "1"},
            "headers": {"authorization": "Bearer secret"},
            "body": "private",
        }
        self.assertEqual(
            {
                "rawPath": "/health",
                "requestContext": {"http": {"method": "GET"}},
                "queryStringParameters": {"a": "1"},
                "headers": "[redacted]",
                "body": "[redacted]",
            },
            redacted_event(event),
        )

    def test_redacted_event_keeps_missing_body_none(self) -> None:
        self.assertIsNone(redacted_event({})["body"])

    def test_jwt_claims_extracts_claims_dict(self) -> None:
        event = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "user_1"}}}}}
        self.assertEqual({"sub": "user_1"}, jwt_claims(event))

    def test_jwt_claims_handles_missing_or_malformed(self) -> None:
        self.assertEqual({}, jwt_claims({}))
        self.assertIsNone(jwt_claims({"requestContext": {"authorizer": {"jwt": {"claims": "nope"}}}}))


class PathParamTest(TestCase):
    def test_extracts_and_unquotes_value(self) -> None:
        self.assertEqual(
            "user 1",
            path_param("/owners/user%201/ai-usage", "/owners/", "/ai-usage", error=BadRequest),
        )

    def test_rejects_wrong_prefix_or_suffix(self) -> None:
        with self.assertRaises(BadRequest) as ctx:
            path_param("/other/x/ai-usage", "/owners/", "/ai-usage", error=BadRequest)
        self.assertEqual("invalid path", str(ctx.exception))

    def test_rejects_empty_value(self) -> None:
        with self.assertRaises(BadRequest) as ctx:
            path_param("/owners//ai-usage", "/owners/", "/ai-usage", error=BadRequest)
        self.assertEqual("path parameter is required", str(ctx.exception))


class LogTest(TestCase):
    def test_log_emits_single_json_line(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            log("error", "boom", event={"rawPath": "/x"})
        self.assertEqual(
            {"level": "error", "message": "boom", "event": {"rawPath": "/x"}},
            json.loads(buffer.getvalue()),
        )
        self.assertEqual(1, buffer.getvalue().count("\n"))
