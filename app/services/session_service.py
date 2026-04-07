from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.orm import (
    LoginMethod,
    SessionHealth,
    SessionHealthEvent,
    SessionTier,
    User,
    UserSession,
)
from app.schemas.sessions import (
    HealthHistoryItem,
    HealthHistoryResponse,
    SessionEntry,
    SessionsListResponse,
    VerifySessionRequest,
    VerifySessionResponse,
)
from app.session_config import session_settings
from app.services.snapshot_persistence import snapshot_exists


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_tier(last_access_at: datetime | None, now: datetime) -> SessionTier:
    if last_access_at is None:
        return SessionTier.cold
    age = (now - _as_utc(last_access_at)).total_seconds()
    if age <= session_settings.tier_hot_access_seconds:
        return SessionTier.hot
    if age <= session_settings.tier_warm_access_seconds:
        return SessionTier.warm
    return SessionTier.cold


def apply_tier(session: UserSession, now: datetime) -> None:
    t = compute_tier(session.last_access_at, now)
    session.tier = t.value


def _interval_seconds_for_tier(tier: str) -> int:
    if tier == SessionTier.hot.value:
        return session_settings.hot_check_interval_seconds
    if tier == SessionTier.warm.value:
        return session_settings.warm_check_interval_seconds
    return session_settings.warm_check_interval_seconds


def compute_next_check_at(
    anchor: datetime, tier: str, now: datetime
) -> datetime | None:
    """Schedule the next background check at anchor + interval + jitter (hot/warm only)."""
    if tier == SessionTier.cold.value:
        return None
    interval = _interval_seconds_for_tier(tier)
    jitter = random.uniform(
        0.0, interval * session_settings.health_check_jitter_fraction
    )
    return anchor + timedelta(seconds=interval + jitter)


async def ensure_user(db: AsyncSession, user_id: str) -> User:
    u = await db.get(User, user_id)
    if u:
        return u
    u = User(id=user_id)
    db.add(u)
    await db.flush()
    return u


async def mint_user(db: AsyncSession) -> str:
    """Create a new user with a server-generated id (UUID)."""
    uid = str(uuid.uuid4())
    db.add(User(id=uid))
    await db.commit()
    return uid


def _entry_from_session(s: UserSession) -> SessionEntry:
    re_auth = s.health == SessionHealth.expired.value
    return SessionEntry(
        session_id=s.id,
        app_package=s.app_package,
        snapshot_id=s.snapshot_id,
        health=s.health,
        last_verified_at=s.last_verified_at,
        last_access_at=s.last_access_at,
        login_method=s.login_method,
        tier=s.tier,
        re_auth_required=re_auth,
    )


async def list_sessions(
    db: AsyncSession, user_id: str, *, logged_in_only: bool = False
) -> SessionsListResponse:
    stmt = select(UserSession).where(UserSession.user_id == user_id)
    if logged_in_only:
        stmt = stmt.where(UserSession.health == SessionHealth.alive.value)
    r = await db.execute(stmt)
    rows = list(r.scalars().all())
    now = utcnow()
    for s in rows:
        apply_tier(s, now)
    return SessionsListResponse(user_id=user_id, sessions=[_entry_from_session(s) for s in rows])


async def verify_session(
    db: AsyncSession,
    user_id: str,
    app_package: str,
    body: VerifySessionRequest | None,
) -> VerifySessionResponse:
    await ensure_user(db, user_id)
    r = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.app_package == app_package,
        )
    )
    session = r.scalar_one_or_none()
    now = utcnow()
    lm = (body.login_method if body and body.login_method else None) or LoginMethod.otp.value
    snap = body.snapshot_id if body else None

    if snap is not None and not await snapshot_exists(db, snap):
        raise ValueError(f"unknown snapshot_id={snap}")

    if session is None:
        session = UserSession(
            user_id=user_id,
            app_package=app_package,
            snapshot_id=snap,
            login_method=lm,
            health=SessionHealth.unknown.value,
            tier=SessionTier.cold.value,
        )
        db.add(session)
        await db.flush()
    else:
        if snap:
            session.snapshot_id = snap
        if body and body.login_method:
            session.login_method = body.login_method

    session.last_access_at = now
    apply_tier(session, now)

    observed, health = await _mock_classify_and_update(db, session, now)
    re_auth = health == SessionHealth.expired.value
    nxt = compute_next_check_at(now, session.tier, now)
    session.next_check_at = nxt
    log.info(
        "session verify user=%s app=%s session_id=%s health=%s tier=%s observed=%s",
        user_id,
        app_package,
        session.id,
        health,
        session.tier,
        observed,
    )
    return VerifySessionResponse(
        session_id=session.id,
        observed=observed,
        health=health,
        tier=session.tier,
        re_auth_required=re_auth,
    )


async def _mock_classify_and_update(
    db: AsyncSession, session: UserSession, now: datetime
) -> tuple[str, str]:
    p = session_settings.mock_logged_in_probability
    logged_in = random.random() < p
    if logged_in:
        observed = "logged_in"
        session.health = SessionHealth.alive.value
    else:
        observed = "expired"
        session.health = SessionHealth.expired.value
    session.last_verified_at = now
    ev = SessionHealthEvent(
        session_id=session.id,
        checked_at=now,
        observed=observed,
        detail="mock vision",
    )
    db.add(ev)
    return observed, session.health


async def _metadata_expire_if_applicable(
    db: AsyncSession, session: UserSession, now: datetime
) -> bool:
    """If session_expires_at is in the past, mark expired without emulator (cheap path)."""
    if session.session_expires_at is None:
        return False
    if _as_utc(session.session_expires_at) >= now:
        return False
    if session.health == SessionHealth.expired.value:
        return False
    session.health = SessionHealth.expired.value
    session.last_verified_at = now
    db.add(
        SessionHealthEvent(
            session_id=session.id,
            checked_at=now,
            observed="expired",
            detail="metadata_ttl",
        )
    )
    return True


async def health_history(
    db: AsyncSession, user_id: str, app_package: str, limit: int
) -> HealthHistoryResponse:
    r = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.app_package == app_package,
        )
    )
    session = r.scalar_one_or_none()
    if session is None:
        log.warning(
            "health_history: session not found user=%s app=%s",
            user_id,
            app_package,
        )
        raise KeyError("session not found")

    r2 = await db.execute(
        select(SessionHealthEvent)
        .where(SessionHealthEvent.session_id == session.id)
        .order_by(SessionHealthEvent.checked_at.desc())
        .limit(limit)
    )
    events = list(r2.scalars().all())
    items = [
        HealthHistoryItem(checked_at=e.checked_at, observed=e.observed, detail=e.detail)
        for e in reversed(events)
    ]
    return HealthHistoryResponse(
        user_id=user_id, app_package=app_package, events=items
    )


async def scan_stale_sessions_for_worker(db: AsyncSession) -> int:
    """
    Hot/warm sessions only (cold: no proactive checks). Rate-limited expensive checks per tick.
    Uses next_check_at + jitter to avoid thundering herds after restarts.
    """
    now = utcnow()
    warm_cutoff = now - timedelta(seconds=session_settings.tier_warm_access_seconds)
    max_checks = session_settings.max_health_checks_per_tick
    fetch_limit = max(max_checks * 50, max_checks)

    stmt = (
        select(UserSession)
        .where(
            UserSession.last_access_at.isnot(None),
            UserSession.last_access_at >= warm_cutoff,
            or_(UserSession.next_check_at.is_(None), UserSession.next_check_at <= now),
        )
        .order_by(UserSession.next_check_at.asc().nullsfirst())
        .limit(fetch_limit)
    )
    r = await db.execute(stmt)
    sessions = list(r.scalars().all())

    checks_done = 0
    for session in sessions:
        if checks_done >= max_checks:
            break

        apply_tier(session, now)
        if session.tier == SessionTier.cold.value:
            session.next_check_at = None
            continue

        if session.next_check_at is None:
            if session.last_verified_at is None:
                session.next_check_at = now
            else:
                session.next_check_at = compute_next_check_at(
                    _as_utc(session.last_verified_at), session.tier, now
                )
            if session.next_check_at is None or session.next_check_at > now:
                continue

        if await _metadata_expire_if_applicable(db, session, now):
            session.next_check_at = compute_next_check_at(now, session.tier, now)
            checks_done += 1
            continue

        await _mock_classify_and_update(db, session, now)
        session.next_check_at = compute_next_check_at(now, session.tier, now)
        checks_done += 1

    return checks_done
