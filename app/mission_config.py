from pydantic_settings import BaseSettings, SettingsConfigDict


class MissionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MISSION_", env_file=".env", extra="ignore")

    identity_gate_probability: float = 0.3
    identity_gate_timeout_seconds: float = 300.0
    webhook_connect_timeout_seconds: float = 5.0
    webhook_read_timeout_seconds: float = 15.0
    execute_sim_seconds: float = 0.8


mission_settings = MissionSettings()
