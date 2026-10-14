import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .models import RunReport
from .project import clean_path, detect_database_type, validate_database_inputs, validate_project_directory
from .runner import print_report, run_project, save_report


def prompt_location(label: str, optional: bool = False) -> Path | None:
    while True:
        raw = input(f"{label}: ").strip()
        if not raw:
            if optional:
                return None
            print("Please enter a path.")
            continue
        path = clean_path(raw)
        if label == "dbt project directory":
            validation_error = validate_project_directory(path)
            if validation_error:
                print(validation_error)
                continue
        if "data directory" in label.lower() and not path.is_dir():
            print(f"Data directory does not exist: {path}")
            continue
        if ("metadata" in label.lower() or "database" in label.lower()) and not path.is_file():
            print(f"Database/metadata file does not exist: {path}")
            continue
        parent = path.parent
        if not parent.exists():
            print(f"Parent directory does not exist: {parent}")
            continue
        return path


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="dbt DuckDB & DuckLake Project Runner")
    parser.add_argument("--project-dir", type=str, help="Path to dbt project directory")
    parser.add_argument("--database", type=str, help="Path to DuckDB database file (.duckdb) or DuckLake catalog (.ducklake)")
    parser.add_argument("--data-dir", type=str, default=None, help="Path to DuckLake Parquet data directory (optional for DuckDB)")
    parser.add_argument("--threads", type=int, default=None, help="Number of dbt execution threads")
    parser.add_argument("--verify-rerun", dest="verify_rerun", action="store_true", default=None, help="Verify repeated execution idempotency")
    parser.add_argument("--no-verify-rerun", dest="verify_rerun", action="store_false", help="Skip repeated execution idempotency check")
    parser.add_argument("--non-interactive", action="store_true", help="Run once without interactive menu and exit")
    return parser.parse_args(args)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print("dbt project runner")
    try:
        config = load_config()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 2

    # Override config with CLI flags if provided
    threads = args.threads or config.threads
    verify_rerun = args.verify_rerun if args.verify_rerun is not None else config.verify_rerun

    project: Path | None = Path(args.project_dir).expanduser().resolve() if args.project_dir else config.project_dir
    database: Path | None = Path(args.database).expanduser().resolve() if args.database else config.database_path
    data_dir: Path | None = Path(args.data_dir).expanduser().resolve() if args.data_dir else config.data_dir

    if not project or not database:
        try:
            if not project:
                project = prompt_location("dbt project directory")
            if not database:
                database = prompt_location("DuckDB database (.duckdb) or DuckLake catalog (.ducklake)")

            assert database is not None
            db_type = detect_database_type(database, data_dir)
            if db_type == "ducklake" and not data_dir:
                data_dir = prompt_location("DuckLake data directory (Parquet files)")
            elif not data_dir:
                data_dir = prompt_location("DuckLake data directory (press Enter to skip for DuckDB)", optional=True)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting before a run was started.")
            return 0

    assert project is not None
    assert database is not None

    if args.non_interactive:
        report = run_project(project, database, data_dir, config, verify_rerun=verify_rerun)
        print_report(report)
        return 0 if report.overall_status == "passed" else 1

    latest: RunReport | None = None
    while True:
        print("\n[run] Run dbt project    [exit] Exit")
        try:
            choice = input("> ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            choice = "exit"
            print()
        if choice in {"run", "r"}:
            try:
                latest = run_project(project, database, data_dir, config, verify_rerun=verify_rerun)
                print_report(latest)
            except Exception as exc:
                print(f"Runner setup failed: {exc}")
                config.run_logs_dir.mkdir(parents=True, exist_ok=True)
                run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
                latest = RunReport(
                    run_id=run_id,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    project_dir=str(project),
                    data_location=str(data_dir) if data_dir else "",
                    ducklake_metadata_location=str(database),
                    overall_status="failed",
                    failure_details=[str(exc)],
                    log_file="",
                    report_file=str(config.run_logs_dir / f"run_{run_id}.json"),
                    config_file=str(config.config_path),
                )
                save_report(latest)
        elif choice in {"exit", "e", "q", "quit"}:
            if latest:
                print_report(latest)
            else:
                print("No dbt run was started in this session.")
            return 0
        else:
            print("Enter 'run' or 'exit'.")
