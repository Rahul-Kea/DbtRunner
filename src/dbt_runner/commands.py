from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import TextIO

from .structured_logging import JsonlEventLogger


def stream_command(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    log: TextIO,
    step_name: str,
    event_logger: JsonlEventLogger | None = None,
    run_id: str = "",
    timeout: float | None = None,
    emit_line_events: bool = False,
) -> tuple[int, float]:
    print(f"\n--- {step_name} ---", flush=True)
    print("$ " + shlex.join(command), flush=True)
    log.write(f"\n--- {step_name} ---\n$ {shlex.join(command)}\n")
    log.flush()
    if event_logger:
        event_logger.emit("command_started", step=step_name, command=command, cwd=str(cwd))
    start = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    output_lines: list[str] = []
    try:
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
            clean_line = line.rstrip("\r\n")
            output_lines.append(clean_line)
            if emit_line_events and event_logger:
                event_logger.emit("command_output", step=step_name, stream="stdout", line=clean_line)
            if timeout and (time.monotonic() - start) > timeout:
                process.terminate()
                raise TimeoutError(f"Step '{step_name}' timed out after {timeout} seconds")
        return_code = process.wait(timeout=max(1.0, (timeout - (time.monotonic() - start))) if timeout else None)
    except (KeyboardInterrupt, Exception):
        process.kill()
        process.wait()
        raise

    duration = time.monotonic() - start
    log.write(f"\n[exit code: {return_code}; duration: {duration:.2f}s]\n")
    log.flush()
    if event_logger:
        last_error = ""
        if return_code != 0:
            error_candidates = [l for l in output_lines if any(k in l.lower() for k in ("error", "fail", "exception"))]
            last_error = error_candidates[-1] if error_candidates else (output_lines[-1] if output_lines else "")
        event_logger.emit(
            "command_finished",
            step=step_name,
            return_code=return_code,
            duration_seconds=duration,
            status="passed" if return_code == 0 else "failed",
            run_id=run_id,
            error_hint=last_error,
        )
    return return_code, duration

