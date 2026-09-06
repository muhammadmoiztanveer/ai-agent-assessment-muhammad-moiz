"""Application configuration.

All runtime configuration is environment-driven via :class:`Settings`
(pydantic-settings). Every field carries a safe default so the system boots and
runs end-to-end with zero credentials in the default DataForSEO ``mock`` mode.

Access configuration through :func:`get_settings`, which returns a process-wide
cached instance.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DataForSeoMode = Literal["mock", "live", "stub"]
LlmMode = Literal["auto", "openai", "mock"]


class Settings(BaseSettings):
    """Strongly-typed application settings loaded from the environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM ---------------------------------------------------------------
    llm_mode: LlmMode = Field(default="auto", alias="LLM_MODE")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0, alias="LLM_TEMPERATURE")
    llm_max_retries: int = Field(default=3, ge=1, le=10, alias="LLM_MAX_RETRIES")

    # --- DataForSEO --------------------------------------------------------
    dataforseo_mode: DataForSeoMode = Field(default="mock", alias="DATAFORSEO_MODE")
    dataforseo_login: str = Field(default="", alias="DATAFORSEO_LOGIN")
    dataforseo_password: str = Field(default="", alias="DATAFORSEO_PASSWORD")
    dataforseo_base_url: str = Field(
        default="https://api.dataforseo.com", alias="DATAFORSEO_BASE_URL"
    )

    # --- Timeouts & retries ------------------------------------------------
    http_connect_timeout_s: float = Field(default=5.0, gt=0, alias="HTTP_CONNECT_TIMEOUT_S")
    http_read_timeout_s: float = Field(default=20.0, gt=0, alias="HTTP_READ_TIMEOUT_S")
    retry_max_attempts: int = Field(default=3, ge=1, le=10, alias="RETRY_MAX_ATTEMPTS")
    retry_base_delay_s: float = Field(default=0.5, gt=0, alias="RETRY_BASE_DELAY_S")
    retry_max_delay_s: float = Field(default=8.0, gt=0, alias="RETRY_MAX_DELAY_S")
    circuit_breaker_fail_threshold: int = Field(
        default=5, ge=1, alias="CIRCUIT_BREAKER_FAIL_THRESHOLD"
    )
    circuit_breaker_cooldown_s: float = Field(
        default=30.0, gt=0, alias="CIRCUIT_BREAKER_COOLDOWN_S"
    )

    # --- Scoring -----------------------------------------------------------
    opp_weight_volume: float = Field(default=0.4, ge=0.0, le=1.0, alias="OPP_WEIGHT_VOLUME")
    opp_weight_difficulty: float = Field(default=0.3, ge=0.0, le=1.0, alias="OPP_WEIGHT_DIFFICULTY")
    opp_weight_gap: float = Field(default=0.3, ge=0.0, le=1.0, alias="OPP_WEIGHT_GAP")
    opp_volume_cap: int = Field(default=10_000, gt=0, alias="OPP_VOLUME_CAP")

    # --- Persistence / app -------------------------------------------------
    database_url: str = Field(default="sqlite:///./data/app.db", alias="DATABASE_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    langchain_tracing_v2: bool = Field(default=False, alias="LANGCHAIN_TRACING_V2")

    # --- Server ------------------------------------------------------------
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, ge=1, le=65535, alias="API_PORT")

    # --- Background run execution (async bonus) ---------------------------
    # Size of the in-process worker pool that executes runs submitted via
    # ``POST /run?async=true``. Kept small by default; a run is coarse-grained.
    run_worker_concurrency: int = Field(default=4, ge=1, le=32, alias="RUN_WORKER_CONCURRENCY")

    # --- Metadata (not env-driven) ----------------------------------------
    api_title: str = "Agentic Search Intelligence System"
    api_version: str = "1.0.0"

    @model_validator(mode="after")
    def _validate_scoring_weights(self) -> Settings:
        """The three opportunity-score weights must sum to 1.0."""
        total = self.opp_weight_volume + self.opp_weight_difficulty + self.opp_weight_gap
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(
                "opportunity-score weights (OPP_WEIGHT_VOLUME + OPP_WEIGHT_DIFFICULTY + "
                f"OPP_WEIGHT_GAP) must sum to 1.0, got {total:.6f}"
            )
        return self

    @model_validator(mode="after")
    def _validate_live_credentials(self) -> Settings:
        """In ``live`` mode DataForSEO credentials are mandatory."""
        has_credentials = bool(self.dataforseo_login and self.dataforseo_password)
        if self.dataforseo_mode == "live" and not has_credentials:
            raise ValueError(
                "DATAFORSEO_MODE=live requires DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD to be set"
            )
        return self

    @model_validator(mode="after")
    def _validate_llm_mode(self) -> Settings:
        """Explicit ``openai`` mode requires an API key (``auto`` falls back to mock)."""
        if self.llm_mode == "openai" and not self.openai_api_key:
            raise ValueError("LLM_MODE=openai requires OPENAI_API_KEY to be set")
        return self

    @property
    def use_real_llm(self) -> bool:
        """Whether to use the real OpenAI-backed client.

        ``openai`` forces it; ``mock`` forbids it; ``auto`` (default) uses the real
        client only when an API key is present, so the system runs keyless by
        default and lights up automatically when a key is provided.
        """
        if self.llm_mode == "openai":
            return True
        if self.llm_mode == "mock":
            return False
        return bool(self.openai_api_key)

    @property
    def is_sqlite(self) -> bool:
        """True when the configured database is SQLite."""
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance."""
    return Settings()
