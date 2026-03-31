from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMULATOR_", env_file=".env", extra="ignore")

    # mock = simulated delays only; sdk = real `emulator` + `adb` (host must have Android SDK).
    backend: Literal["mock", "sdk"] = "mock"
    android_sdk_root: Path | None = None
    avd_name: str = "Pixel_6_API_34"
    emulator_binary: str | None = None
    adb_binary: str | None = None
    # Extra args passed to the emulator CLI (space-separated), e.g. "-no-window -no-audio".
    emulator_extra_args: str = "-no-window -no-audio -gpu swiftshader_indirect -no-boot-anim -netdelay none -netspeed full"
    emulator_port_start: int = 5554
    emulator_boot_completed_timeout_seconds: float = 420.0
    emulator_adb_poll_seconds: float = 2.0
    # After tearing down other emulators, wait before snapshot cold boot (AVD file locks).
    emulator_avd_settle_delay_seconds: float = 1.5

    warm_pool_size: int = 3
    restore_from_snapshot_seconds: float = 2.5
    cold_boot_seconds: float = 8.0
    health_check_interval_seconds: float = 3.0
    max_health_failures_before_replace: int = 2
    mock_unhealthy_probability: float = 0.05
    host: str = "0.0.0.0"
    port: int = 8080

    @field_validator("android_sdk_root", mode="before")
    @classmethod
    def _expand_sdk_root(cls, v: object) -> Path | None:
        if v is None or v == "":
            return None
        return Path(str(v)).expanduser()

    def resolved_android_sdk_root(self) -> Path:
        if self.android_sdk_root is not None:
            return self.android_sdk_root
        import os

        for key in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
            p = os.environ.get(key)
            if p:
                return Path(p).expanduser()
        raise RuntimeError(
            "EMULATOR_BACKEND=sdk requires ANDROID_SDK_ROOT or ANDROID_HOME, or set EMULATOR_ANDROID_SDK_ROOT",
        )


settings = Settings()
