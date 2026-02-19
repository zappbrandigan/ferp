from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FERP_", case_sensitive=False)

    dev_config: bool = False
    script_log_level: str = "info"
    log_level: str = "info"
    log_format: str = "json"


@lru_cache
def get_runtime_config() -> RuntimeConfig:
    return RuntimeConfig()
