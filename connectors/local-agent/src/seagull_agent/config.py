from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from seagull_agent.response_rules import (
    RULE_SOURCE_BUILT_IN_DEFAULTS,
    ResponseRuleResolution,
    default_response_rules,
    resolve_connector_response_rules,
)


@dataclass(frozen=True, slots=True)
class AgentConnectorConfig:
    api_url: str
    agent_handle: str
    token: str | None
    context_dir: Path
    poll_interval_seconds: float = 15.0
    response_rules: ResponseRuleResolution = field(
        default_factory=lambda: ResponseRuleResolution(
            default_response_rules(),
            RULE_SOURCE_BUILT_IN_DEFAULTS,
        )
    )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        api_url: str | None = None,
        agent_handle: str | None = None,
        context_dir: str | None = None,
        poll_interval_seconds: float | None = None,
    ) -> AgentConnectorConfig:
        env = os.environ if environ is None else environ
        file_env = load_env_file(config_file_path(env))
        resolved_api_url = clean_string(api_url) or env_value(env, file_env, "SEAGULL_API_URL")
        resolved_agent_handle = clean_string(agent_handle) or env_value(env, file_env, "SEAGULL_AGENT_HANDLE")
        resolved_context_dir = (
            clean_string(context_dir)
            or env_value(env, file_env, "SEAGULL_AGENT_CONTEXT_DIR")
        )

        missing = []
        if resolved_api_url is None:
            missing.append("SEAGULL_API_URL")
        if resolved_agent_handle is None:
            missing.append("SEAGULL_AGENT_HANDLE")
        if missing:
            raise ConfigError(f"missing required config: {', '.join(missing)}")

        interval = poll_interval_seconds
        if interval is None:
            interval = float(
                env_value(env, file_env, "SEAGULL_AGENT_POLL_INTERVAL")
                or "15"
            )
        if interval <= 0:
            raise ConfigError("SEAGULL_AGENT_POLL_INTERVAL must be positive")

        return cls(
            api_url=resolved_api_url.rstrip("/"),
            agent_handle=resolved_agent_handle,
            token=env_value(env, file_env, "SEAGULL_CONNECTOR_TOKEN"),
            context_dir=Path(resolved_context_dir or ".seagull/agent").expanduser(),
            poll_interval_seconds=interval,
            response_rules=resolve_connector_response_rules(
                rules_file=env_value(env, file_env, "SEAGULL_RESPONSE_RULES_FILE"),
                rules_json=env_value(env, file_env, "SEAGULL_RESPONSE_RULES_JSON"),
            ),
        )


class ConfigError(ValueError):
    pass


def clean_string(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def env_value(env: Mapping[str, str], file_env: Mapping[str, str], name: str) -> str | None:
    return clean_string(env.get(name)) or clean_string(file_env.get(name))


def config_file_path(env: Mapping[str, str]) -> Path | None:
    explicit = clean_string(env.get("SEAGULL_AGENT_ENV_FILE"))
    if explicit is not None:
        return Path(explicit).expanduser()

    local = Path(".seagull/agent/env")
    if local.exists():
        return local

    user = Path("~/.config/seagull/env").expanduser()
    if user.exists():
        return user

    return None


def load_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name:
            continue
        values[name] = unquote_env_value(value.strip())
    return values


def unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
