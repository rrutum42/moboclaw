from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
