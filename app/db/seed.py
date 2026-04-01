from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select

from app.db.engine import AsyncSessionLocal
from app.db.orm import (
    LoginMethod,
    SessionHealth,
    SessionHealthEvent,
    SessionTier,
    User,
    UserSession,
)
from app.services.session_service import apply_tier, utcnow
from app.services.snapshot_persistence import ensure_snapshots_for_seed
from app.services.snapshots import base_snapshot_record, travel_seed_snapshot_record
from app.session_config import session_settings

log = logging.getLogger(__name__)


async def seed_reference_snapshots() -> None:
    """Ensure catalog rows exist for FK references used by seeded sessions."""
    await ensure_snapshots_for_seed(
        [base_snapshot_record(), travel_seed_snapshot_record()]
    )


async def seed_dummy_sessions_if_empty() -> None:
    if not session_settings.seed_dummy_on_empty:
        return

    async with AsyncSessionLocal() as db:
        n = (
            await db.execute(select(func.count()).select_from(User))
        ).scalar_one()
        if n > 0:
            return

        now = utcnow()

        u1 = User(id="demo-user-alpha")
        u2 = User(id="demo-user-beta")
        db.add_all([u1, u2])
        await db.flush()

        s1 = UserSession(
            user_id=u1.id,
            app_package="com.shop.retail",
            snapshot_id="snap-base-default",
            health=SessionHealth.alive.value,
            last_verified_at=now - timedelta(minutes=5),
            last_access_at=now - timedelta(seconds=30),
            login_method=LoginMethod.otp.value,
            tier=SessionTier.cold.value,
        )
        s2 = UserSession(
            user_id=u1.id,
            app_package="com.travel.booking",
            snapshot_id="snap-seed-travel",
            health=SessionHealth.expired.value,
            last_verified_at=now - timedelta(hours=1),
            last_access_at=now - timedelta(seconds=300),
            login_method=LoginMethod.sso.value,
            tier=SessionTier.cold.value,
        )
        s3 = UserSession(
            user_id=u1.id,
            app_package="com.news.reader",
            snapshot_id=None,
            health=SessionHealth.alive.value,
            last_verified_at=now - timedelta(days=1),
            last_access_at=now - timedelta(days=2),
            login_method=LoginMethod.password.value,
            tier=SessionTier.cold.value,
        )
        s4 = UserSession(
            user_id=u2.id,
            app_package="com.social.app",
            snapshot_id="snap-base-default",
            health=SessionHealth.unknown.value,
            last_verified_at=None,
            last_access_at=now - timedelta(hours=6),
            login_method=LoginMethod.otp.value,
            tier=SessionTier.cold.value,
        )
        db.add_all([s1, s2, s3, s4])
        await db.flush()

        for s in (s1, s2, s3, s4):
            apply_tier(s, now)

        db.add_all(
            [
                SessionHealthEvent(
                    session_id=s1.id,
                    checked_at=now - timedelta(minutes=10),
                    observed="logged_in",
                    detail="seed",
                ),
                SessionHealthEvent(
                    session_id=s1.id,
                    checked_at=now - timedelta(minutes=5),
                    observed="logged_in",
                    detail="seed",
                ),
                SessionHealthEvent(
                    session_id=s2.id,
                    checked_at=now - timedelta(hours=1),
                    observed="expired",
                    detail="seed",
                ),
            ]
        )

        await db.commit()
        log.info("seeded dummy users/sessions (empty database)")
