from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_workflows_env(*, override: bool = True) -> Path:
    """Load environment variables from workflows/.env.

    `.env` values override existing variables by default to match local run expectations.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, override=override)
    return env_path
