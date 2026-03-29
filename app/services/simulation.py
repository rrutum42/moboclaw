from __future__ import annotations

import asyncio
import random
import time

from app.config import Settings


async def simulate_boot_seconds(*, from_warm_pool: bool, settings: Settings) -> float:
    target = (
        settings.restore_from_snapshot_seconds
        if from_warm_pool
        else settings.cold_boot_seconds
    )
    jitter = random.uniform(-0.2, 0.2)
    seconds = max(0.1, target + jitter)
    start = time.perf_counter()
    await asyncio.sleep(seconds)
    return time.perf_counter() - start


def mock_health_probe(settings: Settings) -> bool:
    return random.random() > settings.mock_unhealthy_probability
