"""Per-session AVD layout with QCOW2 userdata overlay over a golden image (v1: no adb snapshots)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path

from app.config import Settings

log = logging.getLogger(__name__)

# When ``userdata.useQcow2 = true`` in hardware-qemu.ini (default on modern AVDs), the emulator
# opens this filename — not ``userdata-qemu.img``.
SESSION_USERDATA_QCOW2_NAME = "userdata-qemu.img.qcow2"


def _default_android_avd_home() -> Path:
    return Path(os.environ.get("ANDROID_AVD_HOME", str(Path.home() / ".android" / "avd")))


def golden_avd_dir(settings: Settings) -> Path:
    """Directory `<name>.avd` for the configured AVD name."""
    base = _default_android_avd_home()
    return base / f"{settings.avd_name}.avd"


def golden_userdata_path(settings: Settings) -> Path:
    """Golden AVD userdata image used as qcow2 backing for new sessions from BASE."""
    p = golden_avd_dir(settings) / "userdata-qemu.img"
    if not p.is_file():
        raise RuntimeError(
            f"Golden userdata not found: {p}. Create AVD {settings.avd_name!r} or fix ANDROID_AVD_HOME.",
        )
    return p


def golden_ini_path(settings: Settings) -> Path:
    return _default_android_avd_home() / f"{settings.avd_name}.ini"


def qemu_img_binary(settings: Settings) -> Path:
    if settings.qemu_img_binary:
        return Path(settings.qemu_img_binary).expanduser()
    return settings.resolved_android_sdk_root() / "emulator" / "qemu-img"


async def _run_cmd(*cmd: str, timeout: float = 600.0) -> None:
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
    if rc != 0:
        err = err_b.decode(errors="replace")
        raise RuntimeError(f"command failed rc={rc} cmd={cmd!r}: {err}")


async def qemu_img_detect_backing_format(settings: Settings, backing: Path) -> str:
    """Return format for ``qemu-img create -F`` (must match backing or overlay chain is invalid)."""
    q = qemu_img_binary(settings)
    # Prefer text output first — JSON shape varies across qemu-img versions.
    proc = await asyncio.create_subprocess_exec(
        str(q),
        "info",
        str(backing.resolve()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"qemu-img info failed: {err_b.decode(errors='replace')}")
    text = out_b.decode(errors="replace")
    m = re.search(r"file format:\s*(\S+)", text, re.IGNORECASE)
    if m:
        fmt = m.group(1).lower().strip().rstrip(",")
        if fmt in ("raw", "qcow2", "vmdk"):
            return fmt
    # JSON fallback
    proc2 = await asyncio.create_subprocess_exec(
        str(q),
        "info",
        "--output=json",
        str(backing.resolve()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b2, err_b2 = await proc2.communicate()
    if proc2.returncode == 0:
        try:
            data = json.loads(out_b2.decode())
            fmt = (data.get("format") or "raw").lower()
            if isinstance(fmt, str) and fmt in ("raw", "qcow2", "vmdk"):
                return fmt
        except json.JSONDecodeError:
            pass
    log.warning("qemu-img could not detect format for %s; assuming raw", backing)
    return "raw"


async def qemu_img_create_overlay(
    settings: Settings,
    *,
    backing_file: Path,
    overlay_path: Path,
) -> None:
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    if overlay_path.exists():
        overlay_path.unlink()
    fmt = await qemu_img_detect_backing_format(settings, backing_file)
    q = qemu_img_binary(settings)
    # External snapshot: small overlay; backing stays read-only at the file level.
    await _run_cmd(
        str(q),
        "create",
        "-f",
        "qcow2",
        "-F",
        fmt,
        "-b",
        str(backing_file.resolve()),
        str(overlay_path),
    )
    log.info(
        "qcow2 overlay created overlay=%s backing=%s fmt=%s",
        overlay_path,
        backing_file,
        fmt,
    )


async def qemu_img_check(settings: Settings, *, image: Path) -> None:
    """Fail fast if the overlay is corrupt before the emulator starts."""
    q = qemu_img_binary(settings)
    proc = await asyncio.create_subprocess_exec(
        str(q),
        "check",
        str(image.resolve()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"qemu-img check failed on {image}: {err_b.decode(errors='replace') or out_b.decode(errors='replace')}",
        )


def _rewrite_session_avd_disk_paths(avd_dir: Path) -> None:
    """Point userdata at the qcow2 overlay filename the emulator expects (see ``SESSION_USERDATA_QCOW2_NAME``).

    Modern AVDs set ``userdata.useQcow2 = true``; QEMU then opens ``userdata-qemu.img.qcow2``.
    Writing only ``userdata-qemu.img`` leaves a missing/wrong file and triggers corrupt-image errors.

    Also clears ``disk.dataPartition.initPath`` so the emulator does not copy an init image over the overlay.
    """
    rel = SESSION_USERDATA_QCOW2_NAME
    for name in ("config.ini", "hardware-qemu.ini"):
        path = avd_dir / name
        if not path.is_file():
            continue
        lines_out: list[str] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if re.match(r"^\s*disk\.dataPartition\.initPath\s*=", line):
                lines_out.append("disk.dataPartition.initPath = ")
                continue
            if re.match(r"^\s*disk\.dataPartition\.path\s*=", line):
                lines_out.append(f"disk.dataPartition.path = {rel}")
                continue
            lines_out.append(line)
        path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")

    log.info("rewrote session AVD disk paths for %s (userdata=%s)", avd_dir, rel)


async def qemu_img_convert_flat_qcow2(
    settings: Settings,
    *,
    source_chain: Path,
    dest: Path,
) -> None:
    """Offline flatten to a single qcow2 (compressed). Source must not be in use."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    q = qemu_img_binary(settings)
    await _run_cmd(
        str(q),
        "convert",
        "-O",
        "qcow2",
        "-c",
        "-p",
        str(source_chain.resolve()),
        str(dest),
    )
    log.info("qcow2 flat image written dest=%s", dest)


def _sanitize_avd_token(emulator_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", emulator_id)[:64]


def materialize_session_avd(
    settings: Settings,
    *,
    emulator_id: str,
    userdata_backing: Path,
) -> tuple[Path, str]:
    """Create ANDROID_AVD_HOME layout with one session AVD; userdata is a qcow2 overlay.

    Returns ``(android_avd_home, avd_name)`` for ``emulator -avd <avd_name>`` with
    ``ANDROID_AVD_HOME`` set to ``android_avd_home``.
    """
    root = settings.resolved_qcow2_session_root()
    token = _sanitize_avd_token(emulator_id)
    avd_name = f"moboclaw_{token}"
    android_avd_home = root / token
    avd_dir = android_avd_home / f"{avd_name}.avd"
    if avd_dir.exists():
        shutil.rmtree(avd_dir, ignore_errors=True)
    avd_dir.mkdir(parents=True, exist_ok=True)

    gdir = golden_avd_dir(settings)
    if not gdir.is_dir():
        raise RuntimeError(
            f"golden AVD directory not found: {gdir} "
            f"(install AVD {settings.avd_name!r} or set ANDROID_AVD_HOME)",
        )

    # Copy config fragments; symlink read-only shareable images from golden .avd.
    for name in ("config.ini", "hardware-qemu.ini"):
        src = gdir / name
        if src.is_file():
            shutil.copy2(src, avd_dir / name)

    # Session userdata is ``SESSION_USERDATA_QCOW2_NAME`` (created in ``prepare_session_avd_with_overlay``).
    skip_names = {
        "userdata-qemu.img",
        SESSION_USERDATA_QCOW2_NAME,
        "cache.img",
        "config.ini",
        "hardware-qemu.ini",
        "snapshots",
        "multiinstance.lock",
    }
    for entry in gdir.iterdir():
        if entry.name in skip_names:
            continue
        if entry.is_symlink() or entry.is_file():
            target = avd_dir / entry.name
            if target.exists() or target.is_symlink():
                target.unlink()
            try:
                os.symlink(entry.resolve(), target)
            except OSError:
                shutil.copy2(entry, target)

    snap_dir = avd_dir / "snapshots"
    if snap_dir.exists():
        shutil.rmtree(snap_dir, ignore_errors=True)
    snap_dir.mkdir(exist_ok=True)

    _rewrite_session_avd_disk_paths(avd_dir)

    # Top-level .ini (points at session .avd)
    gini = golden_ini_path(settings)
    if not gini.is_file():
        raise RuntimeError(f"golden AVD ini not found: {gini}")
    ini_text = gini.read_text(encoding="utf-8", errors="replace")
    ini_out = android_avd_home / f"{avd_name}.ini"
    new_dir = str(avd_dir.resolve())
    lines: list[str] = []
    for line in ini_text.splitlines():
        if line.strip().startswith("path=") and not line.strip().startswith("path.rel="):
            lines.append(f"path={new_dir}")
        else:
            lines.append(line)
    if not any(l.strip().startswith("path=") for l in lines if not l.strip().startswith("path.rel=")):
        lines.append(f"path={new_dir}")
    ini_out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Overlay must reference backing userdata (golden or branch flat qcow2).
    if not userdata_backing.is_file():
        raise RuntimeError(f"userdata backing file not found: {userdata_backing}")

    return android_avd_home, avd_name


async def prepare_session_avd_with_overlay(
    settings: Settings,
    *,
    emulator_id: str,
    userdata_backing: Path,
) -> tuple[Path, str]:
    """Create session AVD tree and qcow2 userdata overlay; returns (ANDROID_AVD_HOME, avd_name)."""
    android_avd_home, avd_name = materialize_session_avd(
        settings,
        emulator_id=emulator_id,
        userdata_backing=userdata_backing,
    )
    avd_dir = android_avd_home / f"{avd_name}.avd"
    overlay = avd_dir / SESSION_USERDATA_QCOW2_NAME
    await qemu_img_create_overlay(settings, backing_file=userdata_backing, overlay_path=overlay)
    await qemu_img_check(settings, image=overlay)
    return android_avd_home, avd_name


def destroy_session_avd_tree(settings: Settings, emulator_id: str) -> None:
    root = settings.resolved_qcow2_session_root()
    token = _sanitize_avd_token(emulator_id)
    path = root / token
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        log.info("removed session AVD tree %s", path)


def branches_dir(settings: Settings) -> Path:
    return settings.resolved_qcow2_session_root() / "branches"


def branch_image_path(settings: Settings, snapshot_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", snapshot_id)
    return branches_dir(settings) / f"{safe}.qcow2"
