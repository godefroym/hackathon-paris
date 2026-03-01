from __future__ import annotations

import random


def is_rate_limited_error(exc: Exception) -> bool:
    # Check structured attributes first (more robust against SDK serialization changes).
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status == 429:
        return True
    # Fall back to string matching for SDKs that don't expose status_code.
    lowered = str(exc).lower()
    return (
        "rate limit" in lowered
        or "status 429" in lowered
        or '"code":"1300"' in lowered
        or "'code':'1300'" in lowered
        or "ratelimit" in lowered
    )


def compute_backoff_seconds(
    *,
    attempt: int,
    base_seconds: float,
    max_seconds: float,
) -> float:
    backoff = min(max_seconds, base_seconds * (2 ** attempt))
    jitter = random.uniform(0.0, 0.25 * max(0.2, backoff))
    return backoff + jitter
