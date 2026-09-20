"""Safe runtime configuration for Gateway's paper-only Phase 0 service."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvironmentProfile(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PAPER = "paper"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Settings deliberately expose capabilities, never credentials, to routes."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: EnvironmentProfile = Field(default=EnvironmentProfile.LOCAL, validation_alias=AliasChoices("environment", "GATEWAY_ENV"))
    execution_mode: str = Field(default="paper", validation_alias=AliasChoices("execution_mode", "GATEWAY_EXECUTION_MODE"))
    market_data_provider: str = Field(default="alpaca", validation_alias=AliasChoices("market_data_provider", "MARKET_DATA_PROVIDER"))

    # Phase 6 — OpenBB Open-Data Integration (AGPLv3 — legal review required before prod)
    enable_openbb_data: bool = Field(default=False, validation_alias=AliasChoices("ENABLE_OPENBB_DATA", "enable_openbb_data"))
    enable_openbb_server: bool = Field(default=False, validation_alias=AliasChoices("ENABLE_OPENBB_SERVER", "enable_openbb_server"))

    @field_validator("execution_mode")
    @classmethod
    def paper_only(cls, value: str) -> str:
        if value.lower() != "paper":
            raise ValueError("GATEWAY_EXECUTION_MODE must be 'paper'; live execution is not available")
        return "paper"

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "paper_execution": True,
            "live_execution": False,
            "alpaca_history": self.market_data_provider.lower() == "alpaca",
            "openbb_data": self.enable_openbb_data,
            "openbb_server": self.enable_openbb_server,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
