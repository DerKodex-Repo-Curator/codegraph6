"""Code Analyst agent configuration."""

from __future__ import annotations

from pydantic import SecretStr

from codegraph_shared.settings import BaseAppSettings


class CodeAnalystSettings(BaseAppSettings):
    """Configuration for the Code Analyst MCP agent."""

    service_name: str = "code_analyst"
    host: str = "0.0.0.0"
    port: int = 8003

    anthropic_api_key: SecretStr = SecretStr("")
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 4096
