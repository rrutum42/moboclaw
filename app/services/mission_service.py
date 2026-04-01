from __future__ import annotations

import asyncio
import logging
import random
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.engine import AsyncSessionLocal
from app.db.orm import (
    Mission,
    MissionState,
    MissionTask,
    MissionTaskState,
    SessionHealth,
    UserSession,
)
from app.mission_config import mission_settings
from app.schemas.missions import (
    CreateMissionRequest,
    CreateMissionResponse,
    MissionDetailResponse,
    MissionTaskOut,
    ApproveMissionTaskResponse,
)
from app.services.emulator_service import EmulatorService, emulator_service
from app.services.session_service import ensure_user
from app.services.snapshots import BASE_SNAPSHOT_ID

log = logging.getLogger(__name__)

_gate_events: dict[tuple[str, str], asyncio.Event] = {}
_gate_lock = asyncio.Lock()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _task_to_out(t: MissionTask) -> MissionTaskOut:
    return MissionTaskOut(
        task_id=t.task_id,
        sequence=t.sequence,
        app_package=t.app_package,
        goal=t.goal,
        state=t.state,
        emulator_id=t.emulator_id,
        error_message=t.error_message,
        re_auth_login_method=t.re_auth_login_method,
        identity_gate_notified_at=t.identity_gate_notified_at,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def compute_mission_state(tasks: Iterable[MissionTask]) -> str:
    states = [t.state for t in tasks]
    if any(s == MissionTaskState.failed.value for s in states):
        return MissionState.failed.value
    if any(s == MissionTaskState.re_auth_required.value for s in states):
        return MissionState.re_auth_required.value
    if all(s == MissionTaskState.done.value for s in states):
        return MissionState.done.value
    if all(s == MissionTaskState.queued.value for s in states):
        return MissionState.queued.value
    return MissionState.running.value


def _attach_mission_error_detail_if_needed(m: Mission, tasks: list[MissionTask]) -> None:
    """Set human-readable error_detail when absent (lazy re-auth, first failure)."""
    if m.error_detail:
        return
    if m.state == MissionState.failed.value:
        failed = [t for t in tasks if t.state == MissionTaskState.failed.value]
        if failed:
            t0 = min(failed, key=lambda x: x.sequence)
            m.error_detail = t0.error_message or "task failed"
    elif m.state == MissionState.re_auth_required.value:
        ra = [t for t in tasks if t.state == MissionTaskState.re_auth_required.value]
        if ra:
            t0 = min(ra, key=lambda x: x.sequence)
            lm = t0.re_auth_login_method or "unknown"
            m.error_detail = f"re_auth_required app={t0.app_package} login_method={lm}"


def _re_auth_summary_for_response(
    state: str, tasks: list[MissionTask]
) -> tuple[str | None, str | None]:
    """Mission-level re-auth hints when aggregate state is re_auth_required."""
    if state != MissionState.re_auth_required.value:
        return None, None
    ra = [t for t in tasks if t.state == MissionTaskState.re_auth_required.value]
    if not ra:
        return None, None
    t0 = min(ra, key=lambda x: x.sequence)
    return t0.app_package, t0.re_auth_login_method


async def _get_gate_event(mission_id: str, task_id: str) -> asyncio.Event:
    async with _gate_lock:
        key = (mission_id, task_id)
        if key not in _gate_events:
            _gate_events[key] = asyncio.Event()
        return _gate_events[key]


async def _release_gate_event(mission_id: str, task_id: str) -> None:
    async with _gate_lock:
        _gate_events.pop((mission_id, task_id), None)


async def approve_identity_gate(
    db: AsyncSession,
    mission_id: str,
    task_id: str,
) -> ApproveMissionTaskResponse:
    r = await db.execute(
        select(MissionTask).where(
            MissionTask.mission_id == mission_id,
            MissionTask.task_id == task_id,
        )
    )
    task = r.scalar_one_or_none()
    if task is None:
        log.warning(
            "approve_identity_gate: task not found mission_id=%s task_id=%s",
            mission_id,
            task_id,
        )
        raise HTTPException(status_code=404, detail="task not found")

    if task.state != MissionTaskState.identity_gate.value:
        log.info(
            "approve_identity_gate: no-op mission_id=%s task_id=%s state=%s",
            mission_id,
            task_id,
            task.state,
        )
        return ApproveMissionTaskResponse(
            mission_id=mission_id,
            task_id=task_id,
            state=task.state,
            message="not in identity_gate; no-op",
        )

    ev = await _get_gate_event(mission_id, task_id)
    ev.set()
    log.info(
        "identity_gate resume signaled mission_id=%s task_id=%s",
        mission_id,
        task_id,
    )
    return ApproveMissionTaskResponse(
        mission_id=mission_id,
        task_id=task_id,
        state=task.state,
        message="resume signaled",
    )


async def _load_session_for_app(
    db: AsyncSession, user_id: str, app_package: str
) -> UserSession | None:
    r = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.app_package == app_package,
        )
    )
    return r.scalar_one_or_none()


async def _patch_task(
    task_id: str,
    state: str | None = None,
    emulator_id: str | None = None,
    clear_emulator: bool = False,
    error_message: str | None = None,
    identity_gate_notified_at: datetime | None = None,
) -> MissionTask | None:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(MissionTask).where(MissionTask.task_id == task_id))
        task = r.scalar_one_or_none()
        if not task:
            return None
        if state is not None:
            task.state = state
        if clear_emulator:
            task.emulator_id = None
        elif emulator_id is not None:
            task.emulator_id = emulator_id
        if error_message is not None:
            task.error_message = error_message
        if identity_gate_notified_at is not None:
            task.identity_gate_notified_at = identity_gate_notified_at
        mid = task.mission_id
        await db.commit()
        await _sync_mission_aggregate(mid)
        return task


async def _sync_mission_aggregate(mission_id: str) -> None:
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(MissionTask).where(MissionTask.mission_id == mission_id)
        )
        tasks = list(r.scalars().all())
        m = await db.get(Mission, mission_id)
        if not m:
            return
        m.state = compute_mission_state(tasks)
        _attach_mission_error_detail_if_needed(m, tasks)
        await db.commit()


async def _clear_emulator_on_tasks(task_ids: list[str]) -> None:
    """Clear emulator_id after shared emulator teardown (avoids stale ids in API)."""
    if not task_ids:
        return
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(MissionTask).where(MissionTask.task_id.in_(task_ids)))
        rows = list(r.scalars().all())
        if not rows:
            return
        mid = rows[0].mission_id
        for t in rows:
            t.emulator_id = None
        await db.commit()
        await _sync_mission_aggregate(mid)


async def _fire_webhook(webhook_url: str, payload: dict) -> None:
    timeout = httpx.Timeout(
        connect=mission_settings.webhook_connect_timeout_seconds,
        read=mission_settings.webhook_read_timeout_seconds,
        write=mission_settings.webhook_read_timeout_seconds,
        pool=mission_settings.webhook_connect_timeout_seconds,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        log.info(
            "identity_gate webhook ok url=%s mission_id=%s task_id=%s",
            webhook_url,
            payload.get("mission_id"),
            payload.get("task_id"),
        )
    except Exception as e:
        log.warning("identity_gate webhook failed url=%s: %s", webhook_url, e)


async def _run_mission_task(
    mission_id: str,
    user_id: str,
    task_id: str,
    svc: EmulatorService,
    emu_holder: list[str | None],
) -> bool:
    """One mission task on a shared or new emulator.

    `emu_holder` is a single-element list: ``[None]`` before first provision, then the emulator id
    for all tasks in the app chain. The chain runner destroys once after all tasks (except identity
    gate timeout, which clears the holder after destroy).
    """
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(MissionTask).where(MissionTask.task_id == task_id))
        task = r.scalar_one_or_none()
        if not task or task.mission_id != mission_id:
            log.warning(
                "mission task load failed mission_id=%s task_id=%s (missing or mismatch)",
                mission_id,
                task_id,
            )
            return False

        sess = await _load_session_for_app(db, user_id, task.app_package)
        await db.flush()

        if sess is None:
            log.warning(
                "mission task failed: no session user=%s app=%s task_id=%s",
                user_id,
                task.app_package,
                task_id,
            )
            task.state = MissionTaskState.failed.value
            task.error_message = "no user session for this app; verify session first"
            await db.commit()
            await _sync_mission_aggregate(mission_id)
            return False

        if sess.health == SessionHealth.expired.value:
            log.info(
                "mission task re_auth_required: expired session user=%s app=%s task_id=%s login_method=%s",
                user_id,
                task.app_package,
                task_id,
                sess.login_method,
            )
            task.state = MissionTaskState.re_auth_required.value
            task.re_auth_login_method = sess.login_method
            task.error_message = None
            await db.commit()
            await _sync_mission_aggregate(mission_id)
            return False

        snapshot_id = sess.snapshot_id or BASE_SNAPSHOT_ID
        app_package = task.app_package
        task.state = MissionTaskState.allocating.value
        await db.commit()

    log.info(
        "mission task start mission_id=%s task_id=%s app=%s snapshot=%s",
        mission_id,
        task_id,
        app_package,
        snapshot_id,
    )

    emulator_id: str | None = emu_holder[0]
    try:
        if emulator_id is None:
            prov = await svc.provision(snapshot_id)
            emulator_id = prov.id
            emu_holder[0] = emulator_id

        assert emulator_id is not None
        await _patch_task(task_id, state=MissionTaskState.executing.value, emulator_id=emulator_id)

        await asyncio.sleep(mission_settings.execute_sim_seconds)

        if random.random() < mission_settings.identity_gate_probability:
            log.info(
                "mission task identity_gate entered mission_id=%s task_id=%s",
                mission_id,
                task_id,
            )
            await _patch_task(task_id, state=MissionTaskState.identity_gate.value)
            ev = await _get_gate_event(mission_id, task_id)
            async with AsyncSessionLocal() as db:
                r = await db.execute(select(Mission).where(Mission.id == mission_id))
                m = r.scalar_one_or_none()
                wh = m.webhook_url if m else None
            if wh:
                await _fire_webhook(
                    wh,
                    {
                        "event": "identity_gate",
                        "mission_id": mission_id,
                        "task_id": task_id,
                        "user_id": user_id,
                        "app_package": app_package,
                    },
                )
            async with AsyncSessionLocal() as db:
                r = await db.execute(select(MissionTask).where(MissionTask.task_id == task_id))
                t2 = r.scalar_one_or_none()
                if t2:
                    t2.identity_gate_notified_at = utcnow()
                    await db.commit()

            try:
                await asyncio.wait_for(
                    ev.wait(),
                    timeout=mission_settings.identity_gate_timeout_seconds,
                )
            except asyncio.TimeoutError:
                log.warning(
                    "identity_gate timeout mission_id=%s task_id=%s after=%ss",
                    mission_id,
                    task_id,
                    mission_settings.identity_gate_timeout_seconds,
                )
                await _patch_task(
                    task_id,
                    state=MissionTaskState.failed.value,
                    clear_emulator=True,
                    error_message="identity_gate timeout",
                )
                if emulator_id:
                    try:
                        await svc.destroy_emulator(emulator_id)
                    except Exception as e:
                        log.warning("destroy after gate timeout: %s", e)
                emu_holder[0] = None
                await _release_gate_event(mission_id, task_id)
                return False
            finally:
                await _release_gate_event(mission_id, task_id)

        await _patch_task(task_id, state=MissionTaskState.completing.value)

        await _patch_task(
            task_id,
            state=MissionTaskState.done.value,
            clear_emulator=False,
        )
        log.info(
            "mission task done mission_id=%s task_id=%s app=%s emulator=%s",
            mission_id,
            task_id,
            app_package,
            emulator_id,
        )
        return True

    except ValueError as e:
        log.warning(
            "mission task provision/snapshot error task_id=%s: %s",
            task_id,
            e,
        )
        await _patch_task(
            task_id,
            state=MissionTaskState.failed.value,
            error_message=str(e),
        )
        return False
    except Exception as e:
        log.exception("task %s failed", task_id)
        await _patch_task(
            task_id,
            state=MissionTaskState.failed.value,
            error_message=str(e)[:2000],
        )
        return False


async def _run_app_chain(
    mission_id: str,
    user_id: str,
    chain: list[MissionTask],
    svc: EmulatorService,
) -> None:
    emu_holder: list[str | None] = [None]
    chain_ids = [t.task_id for t in chain]
    try:
        for task in chain:
            ok = await _run_mission_task(mission_id, user_id, task.task_id, svc, emu_holder)
            if not ok:
                break
    finally:
        eid = emu_holder[0]
        if eid:
            try:
                await svc.destroy_emulator(eid)
            except Exception as e:
                log.warning("destroy emulator at end of app chain: %s", e)
        emu_holder[0] = None
        await _clear_emulator_on_tasks(chain_ids)


async def run_mission(mission_id: str, svc: EmulatorService | None = None) -> None:
    svc = svc or emulator_service
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(Mission)
            .where(Mission.id == mission_id)
            .options(selectinload(Mission.tasks))
        )
        m = r.scalar_one_or_none()
        if not m:
            log.warning("run_mission: mission not found id=%s", mission_id)
            return
        m.state = MissionState.running.value
        await db.commit()
        user_id = m.user_id
        tasks = sorted(m.tasks, key=lambda t: t.sequence)

    log.info(
        "mission run start id=%s user=%s task_count=%s apps=%s",
        mission_id,
        user_id,
        len(tasks),
        sorted({t.app_package for t in tasks}),
    )

    by_app: dict[str, list[MissionTask]] = defaultdict(list)
    for t in tasks:
        by_app[t.app_package].append(t)

    results = await asyncio.gather(
        *[_run_app_chain(mission_id, user_id, by_app[app], svc) for app in by_app],
        return_exceptions=True,
    )
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            log.error(
                "mission app chain raised mission_id=%s chain_index=%s",
                mission_id,
                i,
                exc_info=res,
            )

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(MissionTask).where(MissionTask.mission_id == mission_id)
        )
        all_tasks = list(r.scalars().all())
        if any(t.state == MissionTaskState.failed.value for t in all_tasks):
            for t in all_tasks:
                if t.state == MissionTaskState.queued.value:
                    t.state = MissionTaskState.failed.value
                    t.error_message = "skipped: another task failed in this mission"
        await db.commit()

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(MissionTask).where(MissionTask.mission_id == mission_id)
        )
        all_tasks = list(r.scalars().all())
        miss = await db.get(Mission, mission_id)
        if not miss:
            return
        miss.state = compute_mission_state(all_tasks)
        _attach_mission_error_detail_if_needed(miss, all_tasks)
        await db.commit()
        log.info(
            "mission run finished id=%s state=%s error_detail=%s",
            mission_id,
            miss.state,
            miss.error_detail,
        )


async def safe_run_mission(mission_id: str) -> None:
    try:
        await run_mission(mission_id)
    except Exception as e:
        log.exception("mission %s runner crashed", mission_id)
        async with AsyncSessionLocal() as db:
            miss = await db.get(Mission, mission_id)
            if miss:
                miss.state = MissionState.failed.value
                miss.error_detail = str(e)[:2000]
                await db.commit()


async def create_mission(
    db: AsyncSession,
    body: CreateMissionRequest,
) -> CreateMissionResponse:
    await ensure_user(db, body.user_id)
    mission_id = str(uuid.uuid4())
    m = Mission(
        id=mission_id,
        user_id=body.user_id,
        state=MissionState.queued.value,
        webhook_url=body.webhook_url,
    )
    db.add(m)
    task_rows: list[MissionTask] = []
    for seq, tgt in enumerate(body.targets):
        tid = str(uuid.uuid4())
        mt = MissionTask(
            mission_id=mission_id,
            task_id=tid,
            sequence=seq,
            app_package=tgt.app_package,
            goal=tgt.goal,
            state=MissionTaskState.queued.value,
        )
        db.add(mt)
        task_rows.append(mt)
    await db.flush()
    await db.refresh(m)
    for t in task_rows:
        await db.refresh(t)

    log.info(
        "mission created id=%s user=%s tasks=%s webhook=%s",
        mission_id,
        body.user_id,
        len(task_rows),
        bool(body.webhook_url),
    )

    return CreateMissionResponse(
        mission_id=mission_id,
        user_id=body.user_id,
        state=m.state,
        tasks=[_task_to_out(t) for t in task_rows],
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


async def get_mission(db: AsyncSession, mission_id: str) -> MissionDetailResponse | None:
    r = await db.execute(
        select(Mission)
        .where(Mission.id == mission_id)
        .options(selectinload(Mission.tasks))
    )
    m = r.scalar_one_or_none()
    if not m:
        return None
    tasks = sorted(m.tasks, key=lambda t: t.sequence)
    ra_pkg, ra_lm = _re_auth_summary_for_response(m.state, tasks)
    return MissionDetailResponse(
        mission_id=m.id,
        user_id=m.user_id,
        state=m.state,
        webhook_url=m.webhook_url,
        error_detail=m.error_detail,
        re_auth_app_package=ra_pkg,
        re_auth_login_method=ra_lm,
        tasks=[_task_to_out(t) for t in tasks],
        created_at=m.created_at,
        updated_at=m.updated_at,
    )
