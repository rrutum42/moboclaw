"""Per-session AVD layout: full clone of the golden AVD (manual ``cp -r`` parity) + copy-based branch snapshots."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from app.config import Settings

log = logging.getLogger(__name__)


def _default_android_avd_home() -> Path:
    return Path(os.environ.get("ANDROID_AVD_HOME", str(Path.home() / ".android" / "avd")))


def golden_avd_dir(settings: Settings) -> Path:
    """Directory ``<name>.avd`` for the configured golden AVD."""
    base = _default_android_avd_home()
    return base / f"{settings.avd_name}.avd"


def golden_ini_path(settings: Settings) -> Path:
    return _default_android_avd_home() / f"{settings.avd_name}.ini"


def _sanitize_avd_token(emulator_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", emulator_id)[:64]


def _rewrite_golden_absolute_paths_in_session_avd(
    session_avd_dir: Path,
    *,
    golden_avd_dir: Path,
) -> None:
    """Point every absolute path that referenced the golden ``.avd`` dir at ``session_avd_dir``.

    Token replace alone turns ``…/Pixel_6_API_34.avd`` into ``…/moboclaw_….avd`` under the *same*
    parent (``~/.android/avd``), but the real session lives under ``MOBOCLAW_SESSION_ROOT`` — without
    this step, ``hardware-qemu.ini`` still opens disks from the wrong tree and adb stays offline.
    """
    old = str(golden_avd_dir.resolve())
    new = str(session_avd_dir.resolve())
    if old == new:
        return
    n = 0
    for path in session_avd_dir.rglob("*.ini"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if old not in text:
            continue
        path.write_text(text.replace(old, new), encoding="utf-8")
        n += 1
    if n:
        log.info(
            "rewrote golden absolute path in %s session ini file(s) (%s -> session .avd)",
            n,
            golden_avd_dir.name,
        )


def _normalize_cloned_avd_disk_inis(avd_dir: Path) -> None:
    """Make ``config.ini`` / ``hardware-qemu.ini`` consistent for a copied session tree.

    After copytree, ``hardware-qemu.ini`` often still has ``userdata.useQcow2=true`` while
    ``config.ini`` says ``no`` — QEMU follows the hardware file and opens ``userdata-qemu.img.qcow2``,
    which may be missing after clone, so adb never reaches ``device``. ``firstboot.*Snapshot`` can
    also stall boot waiting for snapshots that are not present in the clone.
    """
    for fname in ("config.ini", "hardware-qemu.ini"):
        path = avd_dir / fname
        if not path.is_file():
            continue
        cfg = fname == "config.ini"
        lines_out: list[str] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if re.match(r"^\s*disk\.dataPartition\.initPath\s*=", line):
                lines_out.append("disk.dataPartition.initPath=" if cfg else "disk.dataPartition.initPath = ")
                continue
            if re.match(r"^\s*disk\.dataPartition\.path\s*=", line):
                lines_out.append("disk.dataPartition.path = userdata-qemu.img")
                continue
            if re.match(r"^\s*userdata\.useQcow2\s*=", line):
                lines_out.append("userdata.useQcow2=no" if cfg else "userdata.useQcow2 = no")
                continue
            if re.match(r"^\s*firstboot\.bootFromDownloadableSnapshot\s*=", line):
                lines_out.append(
                    "firstboot.bootFromDownloadableSnapshot=no"
                    if cfg
                    else "firstboot.bootFromDownloadableSnapshot = false"
                )
                continue
            if re.match(r"^\s*firstboot\.bootFromLocalSnapshot\s*=", line):
                lines_out.append(
                    "firstboot.bootFromLocalSnapshot=no"
                    if cfg
                    else "firstboot.bootFromLocalSnapshot = false"
                )
                continue
            if re.match(r"^\s*firstboot\.saveToLocalSnapshot\s*=", line):
                lines_out.append(
                    "firstboot.saveToLocalSnapshot=no"
                    if cfg
                    else "firstboot.saveToLocalSnapshot = false"
                )
                continue
            lines_out.append(line)
        path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    log.info("normalized userdata + firstboot keys in session %s", avd_dir.name)


def _remove_stale_userdata_qcow2_overlay(avd_dir: Path) -> None:
    """Drop overlay file so QEMU does not prefer it over raw ``userdata-qemu.img``."""
    qcow = avd_dir / "userdata-qemu.img.qcow2"
    if qcow.is_file():
        try:
            qcow.unlink()
            log.info("removed userdata-qemu.img.qcow2 from session clone (raw userdata only)")
        except OSError as e:
            log.warning("could not remove userdata-qemu.img.qcow2: %s", e)


def flatten_userdata_qcow2_overlay_into_raw(avd_dir: Path, settings: Settings) -> None:
    """Merge ``userdata-qemu.img.qcow2`` deltas into ``userdata-qemu.img`` before offline copy.

    Writable emulators store app/userdata changes in a qcow2 overlay. Branch restore always
    rewrites inis to raw-only and deletes the overlay; without this commit step, that would drop
    installed apps and session data from captured snapshots.
    """
    qcow = avd_dir / "userdata-qemu.img.qcow2"
    if not qcow.is_file():
        return
    sdk = settings.resolved_android_sdk_root()
    qemu_img = sdk / "emulator" / "qemu-img"
    if not qemu_img.is_file():
        log.warning("qemu-img missing at %s; cannot flatten userdata overlay", qemu_img)
        return
    try:
        subprocess.run(
            [str(qemu_img), "commit", "-p", str(qcow)],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning(
            "qemu-img commit failed for %s (%s); snapshot may omit userdata written to overlay",
            qcow,
            e,
        )
        return
    _remove_stale_userdata_qcow2_overlay(avd_dir)
    _normalize_cloned_avd_disk_inis(avd_dir)
    log.info("flattened userdata qcow2 overlay into raw for %s", avd_dir.name)


def _replace_token_in_ini_tree(root: Path, old: str, new: str) -> None:
    """Global replace in all ``*.ini`` under ``root`` (e.g. ``golden.avd`` → ``moboclaw_….avd``)."""
    for path in root.rglob("*.ini"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if old not in text:
            continue
        path.write_text(text.replace(old, new), encoding="utf-8")


def _rewrite_ini_paths_after_branch_clone(
    android_avd_home: Path,
    *,
    source_android_avd_home: Path,
    source_avd_name: str,
    new_avd_name: str,
) -> None:
    """Rewrite absolute session paths and AVD name tokens after ``copytree`` from a branch snapshot."""
    old_home = str(source_android_avd_home.resolve())
    new_home = str(android_avd_home.resolve())
    for path in android_avd_home.rglob("*.ini"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        text = text.replace(old_home, new_home)
        text = text.replace(source_avd_name, new_avd_name)
        path.write_text(text, encoding="utf-8")


def materialize_session_avd_from_golden(settings: Settings, emulator_id: str) -> tuple[Path, str]:
    """Clone golden ``.avd`` and golden ``.ini``; apply global ``{avd_name}.avd`` rename like ``sed``.

    Returns ``(android_avd_home, avd_name)`` for ``emulator -avd <avd_name>`` with
    ``ANDROID_AVD_HOME`` set to ``android_avd_home``.
    """
    root = settings.resolved_qcow2_session_root()
    token = _sanitize_avd_token(emulator_id)
    avd_name = f"moboclaw_{token}"
    android_avd_home = root / token
    if android_avd_home.exists():
        shutil.rmtree(android_avd_home, ignore_errors=True)
    android_avd_home.mkdir(parents=True, exist_ok=True)

    gdir = golden_avd_dir(settings)
    gini = golden_ini_path(settings)
    if not gdir.is_dir():
        raise RuntimeError(
            f"golden AVD directory not found: {gdir} "
            f"(install AVD {settings.avd_name!r} or set ANDROID_AVD_HOME)",
        )
    if not gini.is_file():
        raise RuntimeError(f"golden AVD ini not found: {gini}")

    avd_dir = android_avd_home / f"{avd_name}.avd"
    shutil.copytree(gdir, avd_dir, symlinks=True, dirs_exist_ok=False)

    snap_dir = avd_dir / "snapshots"
    if snap_dir.exists():
        shutil.rmtree(snap_dir, ignore_errors=True)
    snap_dir.mkdir(exist_ok=True)

    _rewrite_golden_absolute_paths_in_session_avd(avd_dir, golden_avd_dir=gdir)

    golden_avd_token = f"{settings.avd_name}.avd"
    session_avd_token = f"{avd_name}.avd"
    _replace_token_in_ini_tree(avd_dir, golden_avd_token, session_avd_token)

    _normalize_cloned_avd_disk_inis(avd_dir)
    _remove_stale_userdata_qcow2_overlay(avd_dir)

    ini_text = gini.read_text(encoding="utf-8", errors="replace")
    ini_text = ini_text.replace(golden_avd_token, session_avd_token)
    abs_avd = str(avd_dir.resolve())
    out_lines: list[str] = []
    for line in ini_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("path=") and not stripped.startswith("path.rel="):
            out_lines.append(f"path={abs_avd}")
        else:
            out_lines.append(line)
    if not any(
        ln.strip().startswith("path=") and not ln.strip().startswith("path.rel=") for ln in out_lines
    ):
        out_lines.append(f"path={abs_avd}")
    ini_out = android_avd_home / f"{avd_name}.ini"
    ini_out.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    log.info(
        "materialized session AVD from golden emulator_id=%s avd_name=%s home=%s",
        emulator_id,
        avd_name,
        android_avd_home,
    )
    return android_avd_home, avd_name


def materialize_session_avd_from_branch(
    settings: Settings,
    emulator_id: str,
    branch_dir: Path,
    *,
    source_avd_name: str,
    source_android_avd_home: Path,
) -> tuple[Path, str]:
    """Copy a stored branch snapshot tree into a new session directory and rewrite paths/name."""
    if not branch_dir.is_dir():
        raise RuntimeError(f"branch snapshot directory not found: {branch_dir}")

    root = settings.resolved_qcow2_session_root()
    token = _sanitize_avd_token(emulator_id)
    avd_name = f"moboclaw_{token}"
    android_avd_home = root / token
    if android_avd_home.exists():
        shutil.rmtree(android_avd_home, ignore_errors=True)
    android_avd_home.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(branch_dir, android_avd_home, symlinks=True)

    old_ini = android_avd_home / f"{source_avd_name}.ini"
    old_avd = android_avd_home / f"{source_avd_name}.avd"
    new_ini = android_avd_home / f"{avd_name}.ini"
    new_avd = android_avd_home / f"{avd_name}.avd"
    if old_ini.is_file() and old_ini != new_ini:
        if new_ini.exists():
            new_ini.unlink()
        old_ini.rename(new_ini)
    if old_avd.is_dir() and old_avd != new_avd:
        if new_avd.exists():
            shutil.rmtree(new_avd, ignore_errors=True)
        old_avd.rename(new_avd)

    _rewrite_ini_paths_after_branch_clone(
        android_avd_home,
        source_android_avd_home=source_android_avd_home,
        source_avd_name=source_avd_name,
        new_avd_name=avd_name,
    )
    new_avd_dir = android_avd_home / f"{avd_name}.avd"
    if new_avd_dir.is_dir():
        _normalize_cloned_avd_disk_inis(new_avd_dir)
        _remove_stale_userdata_qcow2_overlay(new_avd_dir)
    log.info(
        "materialized session AVD from branch emulator_id=%s avd_name=%s branch=%s",
        emulator_id,
        avd_name,
        branch_dir,
    )
    return android_avd_home, avd_name


async def prepare_session_avd_from_golden(settings: Settings, emulator_id: str) -> tuple[Path, str]:
    return await asyncio.to_thread(materialize_session_avd_from_golden, settings, emulator_id)


async def prepare_session_avd_from_branch(
    settings: Settings,
    emulator_id: str,
    branch_dir: Path,
    *,
    source_avd_name: str,
    source_android_avd_home: Path,
) -> tuple[Path, str]:
    return await asyncio.to_thread(
        materialize_session_avd_from_branch,
        settings,
        emulator_id,
        branch_dir,
        source_avd_name=source_avd_name,
        source_android_avd_home=source_android_avd_home,
    )


def destroy_session_avd_tree(settings: Settings, emulator_id: str) -> None:
    root = settings.resolved_qcow2_session_root()
    token = _sanitize_avd_token(emulator_id)
    path = root / token
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        log.info("removed session AVD tree %s", path)


def branches_dir(settings: Settings) -> Path:
    return settings.resolved_qcow2_session_root() / "branches"


def branch_snapshot_dir(settings: Settings, snapshot_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", snapshot_id)
    return branches_dir(settings) / safe
