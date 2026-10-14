from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO


class JsonlEventLogger:
    """Append machine-readable JSON events while the readable log streams output."""

    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self._file: TextIO | None = None

    def __enter__(self) -> JsonlEventLogger:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._file:
            self._file.close()

    def emit(self, event: str, **fields: object) -> None:
        if self._file is None:
            return
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event": event,
            **fields,
        }
        self._file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._file.flush()
