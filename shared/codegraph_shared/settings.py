"""Base Pydantic Settings shared by all services.

Each agent inherits from ``BaseAppSettings`` and adds its own fields.
All settings can be overridden via environment variables or a ``.env`` file.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseAppSettings(BaseSettings):
    """Common settings for every service in the CodeGraph stack.

    Attributes:
        log_level: Logging verbosity. Defaults to INFO.
        log_json: Emit JSON logs (True) or human-readable (False).
        service_name: Identifies this service in log output.
        neo4j_uri: Bolt URI for the Neo4j database.
        neo4j_user: Neo4j username.
        neo4j_password: Neo4j password (secret).
        redis_url: Redis connection URL.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Observability
    log_level: str = "INFO"
    log_json: bool = True
    service_name: str = "codegraph"

    # Neo4j
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("password")

    # Redis
    redis_url: str = "redis://redis:6379/0"
