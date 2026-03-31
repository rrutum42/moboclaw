from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Body, Depends, HTTPException

from app.models import CreateSnapshotRequest, EmulatorStatusResponse, ProvisionEmulatorRequest

log = logging.getLogger(__name__)
from app.services.emulator_service import EmulatorService, emulator_service

router = APIRouter(tags=["emulators"])


def get_emulator_service() -> EmulatorService:
    return emulator_service


@router.get("/emulators", response_model=list[EmulatorStatusResponse])
async def list_emulators(
    running_only: bool = False,
    svc: EmulatorService = Depends(get_emulator_service),
):
    """List emulators tracked by this service (`emu-…` ids). Set `running_only=true` for RUNNING only."""
    return await svc.list_emulators(running_only=running_only)


@router.post("/emulators", response_model_exclude_none=True)
async def provision_emulator(
    body: ProvisionEmulatorRequest = Body(default_factory=ProvisionEmulatorRequest),
    svc: EmulatorService = Depends(get_emulator_service),
):
    try:
        return await svc.provision(body.snapshot_id)
    except ValueError as e:
        log.warning("provision_emulator rejected: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (TimeoutError, asyncio.TimeoutError) as e:
        log.warning("provision_emulator timed out: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"emulator provision timed out: {e}",
        ) from e
    except (RuntimeError, OSError) as e:
        log.warning("provision_emulator failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/emulators/{emulator_id}/status", response_model=EmulatorStatusResponse)
async def emulator_status(
    emulator_id: str,
    svc: EmulatorService = Depends(get_emulator_service),
):
    try:
        return await svc.status(emulator_id)
    except KeyError:
        log.warning("emulator_status 404 id=%s", emulator_id)
        raise HTTPException(status_code=404, detail="emulator not found") from None


@router.post("/emulators/{emulator_id}/snapshot")
async def create_snapshot(
    emulator_id: str,
    body: CreateSnapshotRequest,
    svc: EmulatorService = Depends(get_emulator_service),
):
    try:
        return await svc.create_snapshot(emulator_id, body)
    except KeyError:
        log.warning("create_snapshot 404 emulator_id=%s", emulator_id)
        raise HTTPException(status_code=404, detail="emulator not found") from None
    except ValueError as e:
        log.warning("create_snapshot conflict emulator_id=%s: %s", emulator_id, e)
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.delete("/emulators/{emulator_id}", status_code=204)
async def delete_emulator(
    emulator_id: str,
    svc: EmulatorService = Depends(get_emulator_service),
):
    try:
        await svc.destroy_emulator(emulator_id)
    except KeyError:
        log.warning("delete_emulator 404 id=%s", emulator_id)
        raise HTTPException(status_code=404, detail="emulator not found") from None


@router.get("/internal/health-events")
async def health_events(
    limit: int = 50,
    svc: EmulatorService = Depends(get_emulator_service),
):
    items = list(svc.health_history)[-limit:]
    return {"events": [e.model_dump(mode="json") for e in items]}
