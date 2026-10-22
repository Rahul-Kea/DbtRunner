from __future__ import annotations

import shlex
import subprocess
import os
import signal
import threading
import queue
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
    output_capture: dict[str, str] | None = None,
    secret_values: list[str] | None = None,
) -> tuple[int, float]:
    print(f"\n--- {step_name} ---", flush=True)
    secrets = [secret for secret in (secret_values or []) if secret]
    display_command = list(command)
    for index, argument in enumerate(display_command):
        for secret in secrets:
            argument = argument.replace(secret, "[REDACTED]")
        display_command[index] = argument
    print("$ " + shlex.join(display_command), flush=True)
    log.write(f"\n--- {step_name} ---\n$ {shlex.join(display_command)}\n")
    log.flush()
    if event_logger:
        event_logger.emit("command_started", step=step_name, command=display_command, cwd=str(cwd))
    start = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        start_new_session=(os.name != "nt"),
    )
    assert process.stdout is not None and process.stderr is not None
    events: queue.Queue[tuple[str, str] | None] = queue.Queue()
    out_lines: list[str] = []
    err_lines: list[str] = []

    def reader(stream: object, name: str) -> None:
        try:
            for line in stream:  # type: ignore[union-attr]
                events.put((name, line))
        finally:
            events.put(None)

    threads = [
        threading.Thread(target=reader, args=(process.stdout, "stdout"), daemon=True),
        threading.Thread(target=reader, args=(process.stderr, "stderr"), daemon=True),
    ]
    for thread in threads:
        thread.start()
    active_readers = len(threads)

    def terminate_group() -> None:
        try:
            if os.name == "nt":
                if process.poll() is None:
                    process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    try:
        while active_readers:
            remaining = None if timeout is None else max(0.01, timeout - (time.monotonic() - start))
            try:
                item = events.get(timeout=remaining)
            except queue.Empty:
                terminate_group()
                raise TimeoutError(f"Step '{step_name}' timed out after {timeout} seconds")
            if item is None:
                active_readers -= 1
                continue
            stream_name, raw_line = item
            line = raw_line
            for secret in secrets:
                line = line.replace(secret, "[REDACTED]")
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
            clean_line = line.rstrip("\r\n")
            (out_lines if stream_name == "stdout" else err_lines).append(clean_line)
            if emit_line_events and event_logger:
                event_logger.emit("command_output", step=step_name, stream=stream_name, line=clean_line)
        return_code = process.wait()
    except Exception:
        terminate_group()
        raise
    finally:
        for thread in threads:
            thread.join(timeout=1)
        if output_capture is not None:
            output_capture["stdout"] = "\n".join(out_lines)
            output_capture["stderr"] = "\n".join(err_lines)

    duration = time.monotonic() - start
    log.write(f"\n[exit code: {return_code}; duration: {duration:.2f}s]\n")
    log.flush()
    if event_logger:
        last_error = ""
        if return_code != 0:
            all_lines = out_lines + err_lines
            error_candidates = [l for l in all_lines if any(k in l.lower() for k in ("error", "fail", "exception"))]
            last_error = error_candidates[-1] if error_candidates else (all_lines[-1] if all_lines else "")
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


class DbtCommandRunner:
    """Small command boundary for timeout, streaming, cancellation, and capture policy."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        command: list[str],
        cwd: Path,
        env: dict[str, str],
        log: TextIO,
        step_name: str,
        event_logger: JsonlEventLogger,
        run_id: str,
        output_capture: dict[str, str],
        secret_values: list[str],
    ) -> tuple[int, float]:
        return stream_command(
            command, cwd, env, log, step_name, event_logger, run_id,
            timeout=self.timeout_seconds, emit_line_events=True,
            output_capture=output_capture, secret_values=secret_values,
        )

