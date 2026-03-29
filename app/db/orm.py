from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SessionHealth(str, enum.Enum):
    alive = "alive"
    expired = "expired"
    unknown = "unknown"


class LoginMethod(str, enum.Enum):
    otp = "otp"
    sso = "sso"
    password = "password"


class SessionTier(str, enum.Enum):
    hot = "hot"
    warm = "warm"
    cold = "cold"


class MissionState(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class MissionTaskState(str, enum.Enum):
    queued = "queued"
    allocating = "allocating"
    executing = "executing"
    identity_gate = "identity_gate"
    completing = "completing"
    done = "done"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sessions: Mapped[list[UserSession]] = relationship(back_populates="user")
    missions: Mapped[list[Mission]] = relationship(back_populates="user")


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (UniqueConstraint("user_id", "app_package", name="uq_user_app"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(256), ForeignKey("users.id", ondelete="CASCADE"))
    app_package: Mapped[str] = mapped_column(String(512))
    snapshot_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    health: Mapped[str] = mapped_column(String(32), default=SessionHealth.unknown.value)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    login_method: Mapped[str] = mapped_column(String(32), default=LoginMethod.otp.value)
    tier: Mapped[str] = mapped_column(String(32), default=SessionTier.cold.value)

    user: Mapped[User] = relationship(back_populates="sessions")
    health_events: Mapped[list[SessionHealthEvent]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SessionHealthEvent(Base):
    __tablename__ = "session_health_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user_sessions.id", ondelete="CASCADE"), index=True
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    observed: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    session: Mapped[UserSession] = relationship(back_populates="health_events")


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(256), ForeignKey("users.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(32), default=MissionState.queued.value)
    webhook_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="missions")
    tasks: Mapped[list[MissionTask]] = relationship(
        back_populates="mission", cascade="all, delete-orphan", order_by="MissionTask.sequence"
    )


class MissionTask(Base):
    __tablename__ = "mission_tasks"
    __table_args__ = (
        UniqueConstraint("mission_id", "sequence", name="uq_mission_task_sequence"),
        Index("ix_mission_tasks_mission_id", "mission_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mission_id: Mapped[str] = mapped_column(String(64), ForeignKey("missions.id", ondelete="CASCADE"))
    task_id: Mapped[str] = mapped_column(String(64), unique=True)
    sequence: Mapped[int] = mapped_column(Integer)
    app_package: Mapped[str] = mapped_column(String(512))
    goal: Mapped[str] = mapped_column(String(2048))
    state: Mapped[str] = mapped_column(String(32), default=MissionTaskState.queued.value)
    emulator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    identity_gate_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    mission: Mapped[Mission] = relationship(back_populates="tasks")
