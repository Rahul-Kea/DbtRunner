from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "runner_config.json"


@dataclass(frozen=True)
class RunnerConfig:
    dbt_package: str
    threads: int
    run_logs_dir: Path
    safe_materializations: tuple[str, ...]
    config_path: Path
    verify_rerun: bool = True
    reuse_environment: bool = True
    timeout_seconds: int = 600
    compile_only: bool = False
    project_dir: Path | None = None
    database_path: Path | None = None
    data_dir: Path | None = None


def load_config(path: Path | None = None) -> RunnerConfig:
    config_path = (path or CONFIG_PATH).resolve()
    try:
        values = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        values = {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid runner configuration {config_path}: {exc}") from exc

    package = values.get("dbt_package", "dbt-duckdb")
    threads = values.get("threads", 1)
    logs_value = values.get("run_logs_dir", "run_logs")
    materializations = values.get(
        "safe_materializations",
        ["table", "view", "incremental", "ephemeral", "materialized_view"],
    )
    verify_rerun = bool(values.get("verify_rerun", True))
    reuse_env = bool(values.get("reuse_environment", True))
    timeout_seconds = int(values.get("timeout_seconds", 600))
    compile_only = bool(values.get("compile_only", False))

    project_dir_val = values.get("project_dir")
    project_dir = Path(project_dir_val).expanduser().resolve() if project_dir_val else None

    db_path_val = values.get("database_path") or values.get("ducklake_metadata_location")
    database_path = Path(db_path_val).expanduser().resolve() if db_path_val else None

    data_dir_val = values.get("data_dir") or values.get("data_location")
    data_dir = Path(data_dir_val).expanduser().resolve() if data_dir_val else None

    if not isinstance(package, str) or not package.strip():
        raise ValueError("runner_config.json: dbt_package must be a non-empty string")
    if not isinstance(threads, int) or isinstance(threads, bool) or threads < 1:
        raise ValueError("runner_config.json: threads must be a positive integer")
    if not isinstance(logs_value, str) or not logs_value.strip():
        raise ValueError("runner_config.json: run_logs_dir must be a non-empty path")
    if (
        not isinstance(materializations, list)
        or not materializations
        or any(not isinstance(value, str) or not value.strip() for value in materializations)
    ):
        raise ValueError("runner_config.json: safe_materializations must be a non-empty list of names")

    logs_path = Path(logs_value).expanduser()
    if not logs_path.is_absolute():
        logs_path = PROJECT_ROOT / logs_path

    return RunnerConfig(
        dbt_package=package.strip(),
        threads=threads,
        run_logs_dir=logs_path.resolve(),
        safe_materializations=tuple(value.strip().lower() for value in materializations),
        config_path=config_path,
        verify_rerun=verify_rerun,
        reuse_environment=reuse_env,
        timeout_seconds=timeout_seconds,
        compile_only=compile_only,
        project_dir=project_dir,
        database_path=database_path,
        data_dir=data_dir,
    )
