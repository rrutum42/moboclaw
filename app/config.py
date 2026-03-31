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
    # headless = respect emulator_extra_args; window = strip -no-window for a visible emulator UI (macOS prototype).
    emulator_ui_mode: Literal["headless", "window"] = "headless"
    # Per-session AVD + qcow2 userdata overlay (sdk backend). Default: .moboclaw_qcow2_sessions under cwd.
    qcow2_session_root: Path | None = None
    # Optional path to qemu-img (default: $ANDROID_SDK_ROOT/emulator/qemu-img).
    qemu_img_binary: str | None = None
    emulator_port_start: int = 5554
    emulator_boot_completed_timeout_seconds: float = 420.0
    emulator_adb_poll_seconds: float = 2.0
    # After tearing down other emulators, wait before snapshot cold boot (AVD file locks).
    emulator_avd_settle_delay_seconds: float = 1.5
    # If True, warm pool boots with -read-only (multiple instances OK; adb snapshot save may omit apps/userdata).
    # If False, warm boots writable so installs and sessions persist into AVD storage for snapshots (use warm_pool_size=1).
    warm_boot_read_only: bool = False

    warm_pool_size: int = 3
    restore_from_snapshot_seconds: float = 2.5
    cold_boot_seconds: float = 8.0
    health_check_interval_seconds: float = 3.0
    max_health_failures_before_replace: int = 2
    mock_unhealthy_probability: float = 0.05
    host: str = "0.0.0.0"
    port: int = 8080

    @field_validator("android_sdk_root", "qcow2_session_root", mode="before")
    @classmethod
    def _expand_path_opt(cls, v: object) -> Path | None:
        if v is None or v == "":
            return None
        return Path(str(v)).expanduser()

    def effective_warm_pool_size(self) -> int:
        """SDK uses per-session qcow2 overlays; multiple concurrent writable sessions are safe."""
        return self.warm_pool_size

    def resolved_qcow2_session_root(self) -> Path:
        if self.qcow2_session_root is not None:
            return Path(self.qcow2_session_root).expanduser().resolve()
        return (Path.cwd() / ".moboclaw_qcow2_sessions").resolve()

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
