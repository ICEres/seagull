from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "seagull.response_rules.v1"

RULE_SOURCE_CONNECTOR_CONFIG = "connector_config"
RULE_SOURCE_BUILT_IN_DEFAULTS = "built_in_defaults"

OUTCOME_DRAFT_REPLY = "draft_reply"
OUTCOME_ASK_HUMAN = "ask_human"
OUTCOME_NO_REPLY = "no_reply"

REPLY_POSTURES = frozenset({OUTCOME_DRAFT_REPLY, OUTCOME_ASK_HUMAN, OUTCOME_NO_REPLY})
TRIGGER_LABELS = frozenset(
    {
        "external_action",
        "secret_or_credential",
        "private_context",
        "ambiguous_request",
        "unsafe_instruction",
    }
)
PROHIBITED_BEHAVIOR_LABELS = frozenset(
    {
        "execute_commands",
        "open_links",
        "send_without_approval",
        "change_rules_from_message_content",
        "include_connector_tokens",
    }
)


@dataclass(frozen=True, slots=True)
class ResponseRules:
    schema_version: str
    persona: str
    style: str
    reply_posture: str
    max_reply_chars: int
    ask_human_triggers: tuple[str, ...]
    prohibited_behavior: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResponseRuleResolution:
    rules: ResponseRules
    source: str
    validation_error: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.validation_error is None


@dataclass(frozen=True, slots=True)
class DraftResult:
    outcome: str
    draft: str | None
    reason: str
    applied_rules: dict[str, Any]
    trigger_labels: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "outcome": self.outcome,
            "reason": self.reason,
            "applied_rules": self.applied_rules,
            "trigger_labels": list(self.trigger_labels),
        }
        if self.draft is not None:
            result["draft"] = self.draft
        return result


class ResponseRuleError(ValueError):
    pass


def resolve_connector_response_rules(
    *,
    rules_file: str | None,
    rules_json: str | None,
) -> ResponseRuleResolution:
    cleaned_file = clean_string(rules_file)
    cleaned_json = clean_string(rules_json)
    if cleaned_file is not None and cleaned_json is not None:
        return invalid_resolution("set only one of SEAGULL_RESPONSE_RULES_FILE or SEAGULL_RESPONSE_RULES_JSON")

    if cleaned_file is None and cleaned_json is None:
        return ResponseRuleResolution(default_response_rules(), RULE_SOURCE_BUILT_IN_DEFAULTS)

    try:
        if cleaned_json is not None:
            raw = json.loads(cleaned_json)
        else:
            raw = json.loads(Path(cleaned_file or "").expanduser().read_text(encoding="utf-8"))
        return ResponseRuleResolution(validate_response_rules(raw), RULE_SOURCE_CONNECTOR_CONFIG)
    except (OSError, json.JSONDecodeError, ResponseRuleError) as exc:
        return invalid_resolution(str(exc))


def validate_response_rules(raw: object) -> ResponseRules:
    if not isinstance(raw, Mapping):
        raise ResponseRuleError("response rules must be a JSON object")

    allowed_fields = {
        "schema_version",
        "persona",
        "style",
        "reply_posture",
        "max_reply_chars",
        "ask_human_triggers",
        "prohibited_behavior",
    }
    unknown = sorted(str(field) for field in raw if field not in allowed_fields)
    if unknown:
        raise ResponseRuleError(f"unknown response rule field(s): {', '.join(unknown)}")

    schema_version = require_string(raw, "schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ResponseRuleError(f"schema_version must be {SCHEMA_VERSION}")

    persona = require_string(raw, "persona")
    style = require_string(raw, "style")
    reply_posture = require_string(raw, "reply_posture")
    if reply_posture not in REPLY_POSTURES:
        raise ResponseRuleError("reply_posture must be draft_reply, ask_human, or no_reply")

    max_reply_chars = raw.get("max_reply_chars")
    if not isinstance(max_reply_chars, int) or isinstance(max_reply_chars, bool):
        raise ResponseRuleError("max_reply_chars must be an integer")
    if max_reply_chars < 1 or max_reply_chars > 4000:
        raise ResponseRuleError("max_reply_chars must be between 1 and 4000")

    ask_human_triggers = require_known_strings(raw, "ask_human_triggers", TRIGGER_LABELS)
    prohibited_behavior = require_known_strings(raw, "prohibited_behavior", PROHIBITED_BEHAVIOR_LABELS)

    return ResponseRules(
        schema_version=schema_version,
        persona=persona,
        style=style,
        reply_posture=reply_posture,
        max_reply_chars=max_reply_chars,
        ask_human_triggers=ask_human_triggers,
        prohibited_behavior=prohibited_behavior,
    )


def default_response_rules() -> ResponseRules:
    return ResponseRules(
        schema_version=SCHEMA_VERSION,
        persona="Conservative Seagull local connector.",
        style="Brief, factual, and cautious.",
        reply_posture=OUTCOME_ASK_HUMAN,
        max_reply_chars=800,
        ask_human_triggers=(
            "external_action",
            "secret_or_credential",
            "private_context",
            "ambiguous_request",
            "unsafe_instruction",
        ),
        prohibited_behavior=(
            "execute_commands",
            "open_links",
            "send_without_approval",
            "change_rules_from_message_content",
            "include_connector_tokens",
        ),
    )


def generate_draft_reply(
    rules: ResponseRuleResolution,
    *,
    delivery_item: Mapping[str, Any],
    thread_context: Mapping[str, Any] | None = None,
) -> DraftResult:
    applied_rules = applied_rules_metadata(rules)
    if rules.validation_error is not None:
        return DraftResult(
            outcome=OUTCOME_ASK_HUMAN,
            draft=None,
            reason=f"response rules are invalid: {rules.validation_error}",
            applied_rules=applied_rules,
        )

    if rules.rules.reply_posture == OUTCOME_ASK_HUMAN:
        return DraftResult(
            outcome=OUTCOME_ASK_HUMAN,
            draft=None,
            reason="response rules require human input",
            applied_rules=applied_rules,
        )

    if rules.rules.reply_posture == OUTCOME_NO_REPLY:
        return DraftResult(
            outcome=OUTCOME_NO_REPLY,
            draft=None,
            reason="response rules specify no_reply",
            applied_rules=applied_rules,
        )

    content = delivery_content(delivery_item)
    detected_triggers = detect_triggers(content)
    configured_triggers = tuple(label for label in detected_triggers if label in rules.rules.ask_human_triggers)
    if configured_triggers:
        return DraftResult(
            outcome=OUTCOME_ASK_HUMAN,
            draft=None,
            reason=f"message matched ask-human trigger(s): {', '.join(configured_triggers)}",
            applied_rules=applied_rules,
            trigger_labels=configured_triggers,
        )

    compact = compact_text(content)
    if not compact:
        return DraftResult(
            outcome=OUTCOME_ASK_HUMAN,
            draft=None,
            reason="message has no inline content to draft from",
            applied_rules=applied_rules,
            trigger_labels=("ambiguous_request",),
        )

    draft = trim_to_limit(f"I can help with this. I received: {compact}", rules.rules.max_reply_chars)
    return DraftResult(
        outcome=OUTCOME_DRAFT_REPLY,
        draft=draft,
        reason="draft generated from connector response rules",
        applied_rules=applied_rules,
    )


def detect_triggers(content: str) -> tuple[str, ...]:
    normalized = content.lower()
    triggers: list[str] = []
    if re.search(r"\b(run|execute|open|click|curl|wget|ssh|delete|write|modify|install)\b", normalized):
        triggers.append("external_action")
    if re.search(r"\b(secret|token|password|passwd|api key|private key|credential)\b", normalized):
        triggers.append("secret_or_credential")
    if re.search(r"\b(private|confidential|dm|direct message|owner-only|owner only)\b", normalized):
        triggers.append("private_context")
    if re.search(r"\b(ignore|bypass|override).{0,40}\b(rule|policy|approval|instruction|safety)\b", normalized):
        triggers.append("unsafe_instruction")
    if "send without approval" in normalized or "do not ask approval" in normalized:
        triggers.append("unsafe_instruction")
    return tuple(dict.fromkeys(triggers))


def applied_rules_metadata(rules: ResponseRuleResolution) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source": rules.source,
        "schema_version": rules.rules.schema_version,
        "reply_posture": rules.rules.reply_posture,
        "max_reply_chars": rules.rules.max_reply_chars,
    }
    if rules.validation_error is not None:
        metadata["validation_error"] = rules.validation_error
    return metadata


def delivery_content(item: Mapping[str, Any]) -> str:
    current_message = item.get("current_message")
    message = item.get("message")
    if isinstance(current_message, Mapping):
        current_content = current_message.get("content_inline")
        if isinstance(current_content, str):
            return current_content
    if isinstance(message, Mapping):
        message_content = message.get("content_inline")
        if isinstance(message_content, str):
            return message_content
    return ""


def compact_text(value: str) -> str:
    return " ".join(value.split())


def trim_to_limit(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return f"{value[: limit - 3].rstrip()}..."[:limit]


def invalid_resolution(message: str) -> ResponseRuleResolution:
    return ResponseRuleResolution(
        rules=default_response_rules(),
        source=RULE_SOURCE_CONNECTOR_CONFIG,
        validation_error=message,
    )


def require_string(raw: Mapping[str, object], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ResponseRuleError(f"{name} must be a non-empty string")
    return value.strip()


def require_known_strings(raw: Mapping[str, object], name: str, known: frozenset[str]) -> tuple[str, ...]:
    value = raw.get(name)
    if not isinstance(value, list):
        raise ResponseRuleError(f"{name} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ResponseRuleError(f"{name} must contain only non-empty strings")
        label = item.strip()
        if label not in known:
            raise ResponseRuleError(f"unknown {name} label: {label}")
        result.append(label)
    return tuple(result)


def clean_string(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
