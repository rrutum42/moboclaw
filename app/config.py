from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMULATOR_", env_file=".env", extra="ignore")

    warm_pool_size: int = 3
    restore_from_snapshot_seconds: float = 2.5
    cold_boot_seconds: float = 8.0
    health_check_interval_seconds: float = 3.0
    max_health_failures_before_replace: int = 2
    mock_unhealthy_probability: float = 0.05
    host: str = "0.0.0.0"
    port: int = 8080


settings = Settings()
