from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SESSION_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./sessions.db"
    tier_hot_access_seconds: int = 86400
    tier_warm_access_seconds: int = 604800
    hot_check_interval_seconds: int = 86400
    warm_check_interval_seconds: int = 604800
    worker_tick_seconds: float = 30.0
    # Spread next_check_at within [0, interval * fraction] after the base interval (reduces thundering herds).
    health_check_jitter_fraction: float = 0.1
    # Cap expensive checks (mock or real emulator) per worker tick.
    max_health_checks_per_tick: int = 20
    mock_logged_in_probability: float = 0.8
    db_connect_retries: int = 30
    db_connect_retry_delay_seconds: float = 1.0
    seed_dummy_on_empty: bool = False


session_settings = SessionSettings()
