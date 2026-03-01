from __future__ import annotations

from typing import Any


def extract_affirmation(payload: dict[str, Any] | None) -> str:
    """Extract the current debate phrase from a payload using compatible keys."""
    if not isinstance(payload, dict):
        return ""

    current = payload.get("affirmation_courante")
    if isinstance(current, str) and current.strip():
        return current.strip()

    fallback = payload.get("affirmation")
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()

    return ""
