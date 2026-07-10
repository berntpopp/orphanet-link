"""Configuration management for orphanet-link.

Settings load from environment variables with the ``ORPHANET_LINK_`` prefix
(nested models use ``__``, e.g. ``ORPHANET_LINK_DATA__BASE_URL=...``) and an
optional ``.env`` file.

orphanet-link has no live API: a local SQLite index, built from the Orphadata
English XML scientific-knowledge files (or fetched prebuilt from a GitHub
Release), is the only data source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from orphanet_link import __version__

# Project root: <repo>/orphanet_link/config.py -> <repo>
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

#: Static Orphadata XML tree (also mirrored on sciences.orphadata.com and the
#: legacy www.orphadata.org host). Files are directly downloadable, no auth.
DEFAULT_BASE_URL = "https://www.orphadata.com/data/xml/"


class OrphanetDataConfig(BaseModel):
    """Local data store: Orphadata English XML -> built SQLite index."""

    data_dir: Path = Field(
        default=_DEFAULT_DATA_DIR,
        description="Directory holding the built SQLite database and download cache.",
    )
    db_filename: str = Field(
        default="orphanet.sqlite",
        description="SQLite database filename within data_dir.",
    )
    base_url: str = Field(
        default=DEFAULT_BASE_URL,
        description="Base URL of the Orphadata XML scientific-knowledge files.",
    )
    download_timeout: int = Field(
        default=300,
        ge=5,
        le=1800,
        description="HTTP timeout (seconds) for downloading an Orphadata file.",
    )
    max_source_bytes: int = Field(
        default=1024 * 1024 * 1024,
        gt=0,
        description="Maximum compressed or raw size of one Orphadata source file.",
    )
    max_bundle_bytes: int = Field(
        default=256 * 1024 * 1024,
        gt=0,
        description="Maximum compressed size of a prebuilt database artifact.",
    )
    max_database_bytes: int = Field(
        default=2 * 1024 * 1024 * 1024,
        gt=0,
        description="Maximum expanded size of a prebuilt SQLite database.",
    )
    max_metadata_bytes: int = Field(
        default=64 * 1024,
        gt=0,
        description="Maximum size of release metadata or checksum sidecars.",
    )
    max_download_seconds: int = Field(
        default=1800,
        gt=0,
        description="Maximum elapsed time for streaming one download.",
    )
    allowed_source_redirect_hosts: list[str] = Field(
        default_factory=list,
        description="Additional exact hosts allowed for Orphadata redirects.",
    )
    user_agent: str = Field(
        default=f"orphanet-link/{__version__} (+https://github.com/berntpopp/orphanet-link)",
        description="User-Agent sent to Orphadata / GitHub.",
    )
    prefer_prebuilt: bool = Field(
        default=True,
        description=(
            "On bootstrap, try to download the prebuilt SQLite from the GitHub "
            "Release artifact before falling back to a local build."
        ),
    )
    release_repo: str = Field(
        default="berntpopp/orphanet-link",
        description="GitHub owner/repo hosting the prebuilt database release assets.",
    )
    release_tag: str = Field(
        default="latest",
        description="Release tag to fetch the prebuilt DB from ('latest' or 'data-<version>').",
    )
    auto_bootstrap: bool = Field(
        default=True,
        description="Ensure the database exists on first use (fetch prebuilt or build).",
    )
    refresh_enabled: bool = Field(
        default=False,
        description=(
            "Run an in-process scheduler (unified/http transports) that conditionally "
            "refreshes the database. Default OFF: Orphanet releases are bi-annual; "
            "refresh is best driven by the CI artifact pipeline + an external cron."
        ),
    )
    refresh_interval_hours: float = Field(
        default=168.0,
        ge=1.0,
        le=2160.0,
        description="Hours between conditional refresh checks (when refresh_enabled).",
    )
    refresh_jitter_seconds: int = Field(
        default=600,
        ge=0,
        le=86400,
        description="Random jitter added to each refresh to avoid thundering herds.",
    )
    build_lock_timeout: int = Field(
        default=1800,
        ge=1,
        le=7200,
        description="Seconds to wait for the cross-process build lock before giving up.",
    )
    cache_size: int = Field(
        default=1024,
        ge=0,
        le=65536,
        description="Max entries in the in-process query cache (0 disables).",
    )
    cache_ttl: int = Field(
        default=3600,
        ge=0,
        le=86400,
        description="Query cache TTL in seconds.",
    )

    @property
    def db_path(self) -> Path:
        """Absolute path to the SQLite database file."""
        return self.data_dir / self.db_filename

    @field_validator("data_dir")
    @classmethod
    def _expand_data_dir(cls, v: Path) -> Path:
        return Path(v).expanduser()

    @field_validator("base_url")
    @classmethod
    def _ensure_trailing_slash(cls, v: str) -> str:
        return v if v.endswith("/") else f"{v}/"


class ServerSettings(BaseSettings):
    """Top-level server settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="ORPHANET_LINK_",
        env_nested_delimiter="__",
    )

    host: str = Field(default="127.0.0.1", description="Server host.")
    port: int = Field(default=8000, ge=1024, le=65535, description="Server port.")
    reload: bool = Field(default=False, description="Enable auto-reload in development.")

    transport: Literal["unified", "http", "stdio"] = Field(
        default="unified",
        description="Server transport mode.",
    )
    mcp_path: str = Field(default="/mcp", description="MCP endpoint path.")

    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins.",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level.",
    )
    log_format: Literal["json", "console"] = Field(
        default="console",
        description="Log format.",
    )

    data: OrphanetDataConfig = Field(
        default_factory=OrphanetDataConfig,
        description="Local data store configuration.",
    )

    @field_validator("mcp_path")
    @classmethod
    def validate_mcp_path(cls, v: str) -> str:
        """Ensure the MCP path starts with a forward slash."""
        return v if v.startswith("/") else f"/{v}"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Parse CORS origins from a comma-separated string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return list(v) if v else []


settings = ServerSettings()


def get_data_config() -> OrphanetDataConfig:
    """Return the active data-store configuration (used by the ingest CLI)."""
    return settings.data
