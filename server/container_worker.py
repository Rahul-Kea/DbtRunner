from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = APP_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dbt_runner.config import load_config
from dbt_runner.models import RunReport
from dbt_runner.runner import run_project, save_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--sandbox-dir", required=True, type=Path)
    parser.add_argument("--verify-rerun", action="store_true")
    parser.add_argument("--compile-only", action="store_true")
    parser.add_argument("--execution-mode", choices=("run", "compile"), default="run")
    parser.add_argument("--full-refresh", action="store_true")
    parser.add_argument("--select")
    parser.add_argument("--run-config", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.environ.setdefault("HOME", "/workspace/home")
    os.environ.setdefault("TMPDIR", "/tmp")
    os.environ["DBT_RUNNER_EXTENSION_CACHE"] = "/opt/duckdb/extensions"
    log_dir = APP_ROOT / "run_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    report_path = log_dir / f"run_{args.run_id}.json"
    exit_path = Path("/workspace/container_done.json")
    exit_code = 1

    try:
        config = replace(
            load_config(path=args.run_config, project_dir=args.project_dir),
            run_logs_dir=log_dir,
            verify_rerun=args.verify_rerun,
            compile_only=args.compile_only or args.execution_mode == "compile",
            execution_mode="compile" if args.compile_only or args.execution_mode == "compile" else "run",
            full_refresh=args.full_refresh,
            select=args.select,
        )
        report = run_project(
            project=args.project_dir,
            database_or_data=args.database,
            metadata_or_none=args.data_dir,
            config=config,
            verify_rerun=args.verify_rerun,
            run_id=args.run_id,
            sandbox_dir=args.sandbox_dir,
        )
        exit_code = 0 if report.overall_status in {"passed", "needs_configuration"} else 1
    except Exception as exc:
        report = RunReport(
            run_id=args.run_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            project_dir=str(args.project_dir),
            data_location=str(args.data_dir) if args.data_dir else "",
            ducklake_metadata_location=str(args.database),
            overall_status="failed",
            failure_details=[f"Container runner failed: {exc}"],
            log_file=str(log_dir / f"run_{args.run_id}.log"),
            structured_log_file=str(log_dir / f"run_{args.run_id}.events.jsonl"),
            report_file=str(report_path),
            config_file=str(APP_ROOT / "runner_config.json"),
        )
        save_report(report)
        try:
            with (log_dir / f"run_{args.run_id}.log").open("a", encoding="utf-8") as log:
                log.write(f"\nContainer runner failed: {exc}\n")
        except OSError:
            pass
    finally:
        exit_path.write_text(json.dumps({"exit_code": exit_code}), encoding="utf-8")

    # The session container's PID 1 is an idle shell process. This worker is
    # invoked with `docker exec`, so it must exit to release its run resources.


if __name__ == "__main__":
    main()
