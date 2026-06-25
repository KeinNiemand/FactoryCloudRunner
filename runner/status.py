from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_status(
    path: Path,
    *,
    run_id: str,
    state: str,
    started_at: str,
    exit_code: int | None,
    error: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "state": state,
                "exit_code": exit_code,
                "error": error,
                "started_at": started_at,
                "finished_at": utc_now(),
                "llamafactory_commit": os.getenv("LLAMAFACTORY_COMMIT", "unknown"),
                "llamafactory_dirty": os.getenv("LLAMAFACTORY_DIRTY", "unknown"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
