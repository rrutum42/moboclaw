from __future__ import annotations

import uuid


def new_emulator_id() -> str:
    return f"emu-{uuid.uuid4().hex[:12]}"


def new_snapshot_id() -> str:
    return f"snap-{uuid.uuid4().hex[:12]}"
