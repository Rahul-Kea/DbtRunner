from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from dbt_runner.commands import stream_command


def test_stream_command_captures_separate_streams_and_redacts(tmp_path: Path) -> None:
    output: dict[str, str] = {}
    log = io.StringIO()
    command = [sys.executable, "-c", "import sys; print('token-value'); print('failure-detail', file=sys.stderr)"]

    code, _ = stream_command(command, tmp_path, {}, log, "capture", output_capture=output, secret_values=["token-value"])

    assert code == 0
    assert output["stdout"] == "[REDACTED]"
    assert output["stderr"] == "failure-detail"
    assert "token-value" not in log.getvalue()


def test_stream_command_enforces_timeout(tmp_path: Path) -> None:
    with pytest.raises(TimeoutError):
        stream_command(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            tmp_path, {}, io.StringIO(), "timeout", timeout=0.1,
        )
