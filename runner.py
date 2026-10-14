"""Compatibility entrypoint for the modular dbt runner.

Run with ``python3 runner.py``; implementation lives under ``src/dbt_runner``.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dbt_runner.commands import stream_command
from dbt_runner.cli import main
from dbt_runner.config import RunnerConfig, load_config
from dbt_runner.models import RunReport, StepResult
from dbt_runner.project import (
    clean_path,
    copy_data_to_sandbox,
    copy_project_to_sandbox,
    detect_database_type,
    read_profile_name,
    validate_database_inputs,
    validate_project_directory,
    write_profile,
    yaml_quote,
)
from dbt_runner.runner import DBT_PACKAGE, RUNS_DIR, print_report, run_project, save_report
from dbt_runner.validation import (
    core_type_family,
    expected_relations,
    parse_log_results,
    parse_run_results,
    validate_catalog,
    validate_materialization_policy,
    verify_dag,
    verify_database_objects_direct,
)

if __name__ == "__main__":
    raise SystemExit(main())
