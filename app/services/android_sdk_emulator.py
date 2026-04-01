"""Start/stop Android Emulator CLI instances and drive them via adb."""

from __future__ import annotations

import asyncio
import logging
import shlex
import time
from pathlib import Path

from app.config import Settings

log = logging.getLogger(__name__)


def sdk_emulator_path(settings: Settings) -> Path:
    root = settings.resolved_android_sdk_root()
    if settings.emulator_binary:
        return Path(settings.emulator_binary).expanduser()
    return root / "emulator" / "emulator"


def sdk_adb_path(settings: Settings) -> Path:
    root = settings.resolved_android_sdk_root()
    if settings.adb_binary:
        return Path(settings.adb_binary).expanduser()
    return root / "platform-tools" / "adb"


def _serial_for_console_port(console_port: int) -> str:
    return f"emulator-{console_port}"


def _split_extra_args(extra: str) -> list[str]:
    extra = extra.strip()
    if not extra:
        return []
    return shlex.split(extra)


def emulator_cli_extra_args(settings: Settings) -> list[str]:
    """Extra emulator argv; strips ``-no-window`` when ``emulator_ui_mode=window``."""
    parts = _split_extra_args(settings.emulator_extra_args)
    if settings.emulator_ui_mode == "window":
        parts = [p for p in parts if p != "-no-window"]
    return parts


async def _run_text(
    *cmd: str,
    timeout: float = 120.0,
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise
    rc = proc.returncode if proc.returncode is not None else -1
    return rc, out_b.decode(errors="replace"), err_b.decode(errors="replace")


def _serial_is_device_line(line: str, serial: str) -> bool:
    parts = line.split()
    return len(parts) >= 2 and parts[0] == serial and parts[1] == "device"


def _emulator_process_exited(proc: asyncio.subprocess.Process | None) -> bool:
    return proc is not None and proc.returncode is not None


async def adb_wait_for_device(
    adb: Path,
    serial: str,
    timeout: float,
    *,
    proc: asyncio.subprocess.Process | None = None,
) -> None:
    """Poll `adb devices` until the emulator serial is listed, then `wait-for-device`."""
    deadline = time.monotonic() + timeout
    listed = False
    last_log = time.monotonic()
    while time.monotonic() < deadline:
        if _emulator_process_exited(proc):
            raise RuntimeError(
                f"emulator process exited with code {proc.returncode} before adb listed {serial}",
            )
        if time.monotonic() - last_log >= 15.0:
            remaining = max(0.0, deadline - time.monotonic())
            log.info(
                "adb still waiting for device %s (%.0fs remaining of %.0fs timeout)",
                serial,
                remaining,
                timeout,
            )
            last_log = time.monotonic()
        code, out, _ = await _run_text(str(adb), "devices", timeout=30.0)
        if code == 0:
            for line in out.splitlines():
                if _serial_is_device_line(line.strip(), serial):
                    listed = True
                    break
        if listed:
            break
        await asyncio.sleep(1.0)
    else:
        raise TimeoutError(f"emulator serial never listed in adb devices: {serial}")

    proc = await asyncio.create_subprocess_exec(
        str(adb),
        "-s",
        serial,
        "wait-for-device",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    remaining = max(5.0, deadline - time.monotonic())
    try:
        await asyncio.wait_for(proc.wait(), timeout=remaining)
    except TimeoutError:
        proc.kill()
        raise TimeoutError(f"adb wait-for-device timed out: {serial}") from None
    if proc.returncode != 0:
        raise RuntimeError(f"adb wait-for-device failed for {serial}")


async def adb_wait_boot_completed(
    adb: Path,
    serial: str,
    settings: Settings,
    *,
    proc: asyncio.subprocess.Process | None = None,
) -> None:
    deadline = time.monotonic() + settings.emulator_boot_completed_timeout_seconds
    poll = max(0.5, settings.emulator_adb_poll_seconds)
    last_log = time.monotonic()
    while time.monotonic() < deadline:
        if _emulator_process_exited(proc):
            raise RuntimeError(
                f"emulator process exited with code {proc.returncode} during boot {serial}",
            )
        if time.monotonic() - last_log >= 20.0:
            log.info(
                "adb still waiting for boot_completed on %s (sys.boot_completed != 1 yet)",
                serial,
            )
            last_log = time.monotonic()
        code, out, _ = await _run_text(
            str(adb),
            "-s",
            serial,
            "shell",
            "getprop",
            "sys.boot_completed",
            timeout=60.0,
        )
        if code == 0 and out.strip() == "1":
            return
        await asyncio.sleep(poll)
    raise TimeoutError(f"sys.boot_completed != 1 for {serial}")


async def adb_health_ok(adb: Path, serial: str) -> bool:
    code, out, _ = await _run_text(
        str(adb),
        "-s",
        serial,
        "shell",
        "getprop",
        "sys.boot_completed",
        timeout=30.0,
    )
    return code == 0 and out.strip() == "1"


async def adb_emu_kill(adb: Path, serial: str) -> None:
    await _run_text(str(adb), "-s", serial, "emu", "kill", timeout=60.0)


async def adb_shell_sync(adb: Path, serial: str) -> bool:
    """Flush filesystem buffers before offline userdata capture (best-effort)."""
    code, _out, err = await _run_text(str(adb), "-s", serial, "shell", "sync", timeout=120.0)
    if code != 0:
        log.warning("adb shell sync failed serial=%s rc=%s: %s", serial, code, err)
        return False
    return True


async def start_emulator_process(
    settings: Settings,
    *,
    console_port: int,
    read_only_avd: bool,
    android_avd_home: Path | None = None,
    avd_name: str | None = None,
) -> asyncio.subprocess.Process:
    """Start emulator with a cloned session AVD (no quick-boot snapshot load/save)."""
    sdk = settings.resolved_android_sdk_root()
    emu = sdk_emulator_path(settings)
    import os

    env = {
        **os.environ,
        "ANDROID_SDK_ROOT": str(sdk),
        "ANDROID_HOME": str(sdk),
    }
    if android_avd_home is not None:
        env["ANDROID_AVD_HOME"] = str(android_avd_home.resolve())
    name = avd_name or settings.avd_name
    cmd: list[str] = [
        str(emu),
        "-avd",
        name,
        "-port",
        str(console_port),
    ]
    if read_only_avd:
        cmd.append("-read-only")
    cmd.append("-no-snapshot-load")
    # Avoid "unable to lock snapshot save on exit!" crash dialog when teardown races qcow2/session AVD.
    cmd.append("-no-snapshot-save")
    cmd.extend(emulator_cli_extra_args(settings))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    return proc


async def drain_emulator_stderr_to_log(
    proc: asyncio.subprocess.Process,
    *,
    max_info_lines: int = 40,
) -> None:
    """Stream emulator stderr into logs (first lines at INFO, rest DEBUG)."""
    if proc.stderr is None:
        return
    n = 0
    try:
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            n += 1
            text = line.decode(errors="replace").rstrip()
            if not text:
                continue
            if n <= max_info_lines:
                log.info("emulator stderr: %s", text)
            else:
                log.debug("emulator stderr: %s", text)
    except Exception:
        log.exception("drain_emulator_stderr_to_log failed")


async def kill_emulator(
    adb: Path,
    proc: asyncio.subprocess.Process | None,
    serial: str | None,
) -> None:
    if serial:
        try:
            await adb_emu_kill(adb, serial)
        except Exception:
            log.exception("adb emu kill failed serial=%s", serial)
    if proc is None:
        return
    try:
        # After `adb emu kill`, the emulator should exit on its own. Sending SIGTERM to the
        # wrapper immediately races QEMU teardown and often triggers "qemu-system-* quit
        # unexpectedly" on macOS. Prefer waiting for a clean exit first.
        if serial:
            try:
                await asyncio.wait_for(proc.wait(), timeout=60.0)
                return
            except TimeoutError:
                log.warning(
                    "emulator pid=%s did not exit within 60s after adb emu kill; sending SIGTERM",
                    proc.pid,
                )
        try:
            proc.terminate()
        except ProcessLookupError:
            return
        await asyncio.wait_for(proc.wait(), timeout=15.0)
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            return
        try:
            await proc.wait()
        except Exception:
            log.exception("emulator process kill wait failed")
    except ProcessLookupError:
        pass
    except Exception:
        log.exception("emulator process teardown")
