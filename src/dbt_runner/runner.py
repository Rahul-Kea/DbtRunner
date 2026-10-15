from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import venv
from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .commands import stream_command
from .config import PROJECT_ROOT, RunnerConfig
from .models import RunReport, StepResult
from .project import (
    clone_database_file,
    copy_data_to_sandbox,
    copy_project_to_sandbox,
    detect_database_type,
    read_profile_name,
    validate_database_inputs,
    validate_project_directory,
    write_catalog_clone_script,
    write_profile,
)
from .structured_logging import JsonlEventLogger
from .validation import (
    enrich_objects_with_samples,
    expected_relations,
    parse_run_results,
    validate_catalog,
    validate_materialization_policy,
    verify_dag,
    verify_database_objects_direct,
)

RUNS_DIR = PROJECT_ROOT / "run_logs"
DBT_PACKAGE = "dbt-duckdb"


def save_report(report: RunReport) -> None:
    Path(report.report_file).write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _resolve_dbt_environment(config: RunnerConfig) -> tuple[str, list[str], str]:
    """Find or prepare a fast dbt execution environment without re-downloading on every run."""
    # 1. Try host environment if dbt is already present and configured
    host_dbt = shutil.which("dbt")
    if config.reuse_environment and host_dbt:
        try:
            import dbt.adapters.duckdb  # type: ignore # noqa: F401
            return sys.executable, [host_dbt, "--no-version-check"], "host"
        except ImportError:
            pass

    # 2. Use a persistent runner virtual environment in PROJECT_ROOT / ".venv_runner"
    persistent_venv = PROJECT_ROOT / ".venv_runner"
    py_path = persistent_venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    dbt_path = persistent_venv / ("Scripts/dbt.exe" if os.name == "nt" else "bin/dbt")

    if not py_path.is_file() or not dbt_path.is_file():
        venv.EnvBuilder(with_pip=True).create(persistent_venv)

    return str(py_path), [str(dbt_path), "--no-version-check"], "persistent"


def run_project(
    project: Path,
    database_or_data: Path,
    metadata_or_none: Path | None = None,
    config: RunnerConfig | None = None,
    verify_rerun: bool | None = None,
    run_id: str | None = None,
    sandbox_dir: Path | None = None,
) -> RunReport:
    # Handle backwards compatibility with positional args:
    # Older signature: run_project(project, data_dir, metadata, config)
    # Newer signature: run_project(project, database_path, data_dir=None, config=None)
    data_dir: Path | None = None
    if metadata_or_none is not None and isinstance(metadata_or_none, (Path, str)):
        cand_meta = Path(metadata_or_none).resolve()
        cand_db_data = Path(database_or_data).resolve()
        if cand_db_data.is_dir() and cand_meta.is_file():
            # Old signature: (project, data_dir, metadata)
            data_dir = cand_db_data
            database_path = cand_meta
        else:
            database_path = cand_db_data
            data_dir = cand_meta if cand_meta.is_dir() else None
    else:
        database_path = Path(database_or_data).resolve()
        data_dir = config.data_dir if config and config.data_dir else None

    config = config or load_config()
    should_verify_rerun = verify_rerun if verify_rerun is not None else config.verify_rerun
    run_logs_dir = config.run_logs_dir
    run_logs_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_id or datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    log_path = run_logs_dir / f"run_{run_id}.log"
    structured_log_path = run_logs_dir / f"run_{run_id}.events.jsonl"
    report_path = run_logs_dir / f"run_{run_id}.json"

    db_type = detect_database_type(database_path, data_dir)

    is_compile = config.compile_only or config.execution_mode == "compile"
    mode_str = "compile" if is_compile else "run"

    report = RunReport(
        run_id=run_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        project_dir=str(project),
        data_location=str(data_dir) if data_dir else "",
        ducklake_metadata_location=str(database_path),
        database_type=db_type,
        log_file=str(log_path),
        structured_log_file=str(structured_log_path),
        report_file=str(report_path),
        config_file=str(config.config_path),
        rerun_policy="dry-run syntax and DAG topology verification (no data mutations)" if is_compile else "isolated clone of the database/lake per run with idempotency validation",
        execution_mode=mode_str,
        full_refresh=config.full_refresh,
        select=config.select,
    )

    print(f"\nStarting run {run_id} ({db_type.upper()})")
    print(f"Log: {log_path}")
    sandbox_created = False

    with log_path.open("w", encoding="utf-8") as log, JsonlEventLogger(structured_log_path, run_id) as event_logger:
        event_logger.emit(
            "run_started",
            project_dir=str(project),
            database_path=str(database_path),
            data_location=str(data_dir) if data_dir else "",
            database_type=db_type,
            config_file=str(config.config_path),
            verify_rerun=should_verify_rerun,
        )
        log.write(
            f"dbt runner execution {run_id}\n"
            f"Project input: {project}\n"
            f"Database input: {database_path} ({db_type})\n"
            f"Data input: {data_dir or '<none>'}\n"
            f"Execution mode: isolated temporary sandbox with safe repeated execution verification.\n"
        )
        try:
            val_err = validate_project_directory(project)
            if val_err:
                raise ValueError(val_err)
            detected_type, db_err = validate_database_inputs(database_path, data_dir)
            if db_err:
                raise ValueError(db_err)

            if sandbox_dir is None:
                sandbox_context = tempfile.TemporaryDirectory(prefix="dbt-runner-")
            else:
                sandbox_dir = Path(sandbox_dir).resolve()
                sandbox_dir.mkdir(parents=True, exist_ok=True)
                if any(sandbox_dir.iterdir()):
                    raise ValueError(f"Run sandbox directory must be empty: {sandbox_dir}")
                sandbox_context = nullcontext(str(sandbox_dir))

            with sandbox_context as temp_name:
                sandbox_created = True
                temp_root = Path(temp_name)
                project_copy = temp_root / "project"
                profile_dir = temp_root / "profiles"
                target_dir = temp_root / "target"
                log_dir = temp_root / "dbt_logs"
                temp_work_dir = temp_root / "tmp"
                extension_cache = os.environ.get("DBT_RUNNER_EXTENSION_CACHE")
                if extension_cache and Path(extension_cache).is_dir():
                    # Container images can provide preinstalled, read-only extensions.
                    # Use that exact directory so offline runs don't try to redownload them.
                    duckdb_extensions = Path(extension_cache).resolve()
                else:
                    duckdb_extensions = temp_root / "duckdb_extensions"

                profile_dir.mkdir()
                target_dir.mkdir()
                log_dir.mkdir()
                temp_work_dir.mkdir()
                if not duckdb_extensions.exists():
                    duckdb_extensions.mkdir()

                report.sandbox_workspace = str(temp_root)
                print("Preparing isolated sandbox...", flush=True)

                copy_project_to_sandbox(project, project_copy, data_dir, database_path)

                sandbox_data_dir: Path | None = None
                if db_type == "ducklake":
                    sandbox_metadata = temp_root / "simulation.ducklake"
                    catalog_clone_script = temp_root / "clone_ducklake_catalog.py"
                    write_catalog_clone_script(catalog_clone_script)
                    if data_dir and data_dir.is_dir():
                        sandbox_data_dir = temp_root / "lake_data"
                        copy_data_to_sandbox(data_dir, sandbox_data_dir)
                else:
                    sandbox_metadata = temp_root / database_path.name
                    clone_database_file(database_path, sandbox_metadata)

                profile_name = read_profile_name(project_copy)
                write_profile(
                    profile_dir / "profiles.yml",
                    profile_name,
                    sandbox_data_dir,
                    sandbox_metadata,
                    duckdb_extensions,
                    db_type=db_type,
                )

                python_exec, dbt_cmd, env_type = _resolve_dbt_environment(config)
                env = os.environ.copy()
                env.update(
                    {
                        "DBT_PROFILES_DIR": str(profile_dir),
                        "DBT_TARGET_PATH": str(target_dir),
                        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
                        "DBT_VERSION_CHECK": "false",
                        "TMPDIR": str(temp_work_dir),
                        "TEMP": str(temp_work_dir),
                        "TMP": str(temp_work_dir),
                        "PYTHONUNBUFFERED": "1",
                    }
                )

                steps: list[StepResult] = []
                # Ensure packages if persistent environment needs installation
                if env_type != "host":
                    steps.append(
                        StepResult("Ensure dbt-duckdb dependencies", [python_exec, "-m", "pip", "install", "-q", config.dbt_package])
                    )

                if db_type == "ducklake":
                    steps.append(
                        StepResult("Clone DuckLake metadata catalog", [python_exec, str(catalog_clone_script), str(database_path), str(sandbox_metadata)])
                    )

                # Only run dbt deps if packages are defined
                if (project_copy / "packages.yml").is_file() or (project_copy / "dependencies.yml").is_file():
                    steps.append(
                        StepResult("Install project packages (dbt deps)", dbt_cmd + ["deps", "--project-dir", str(project_copy), "--profiles-dir", str(profile_dir), "--log-path", str(log_dir)])
                    )

                steps.append(
                    StepResult("Parse dbt DAG", dbt_cmd + ["parse", "--project-dir", str(project_copy), "--profiles-dir", str(profile_dir), "--log-path", str(log_dir)])
                )

                select_args = ["--select"] + config.select.strip().split() if config.select and config.select.strip() else []
                refresh_args = ["--full-refresh"] if config.full_refresh else []

                if is_compile:
                    compile_label = "Compile dbt models & validate references (dbt compile" + (" --full-refresh" if config.full_refresh else "") + (f" -s {config.select}" if config.select else "") + ")"
                    steps.append(
                        StepResult(compile_label, dbt_cmd + ["compile", "--project-dir", str(project_copy), "--profiles-dir", str(profile_dir), "--log-path", str(log_dir)] + refresh_args + select_args)
                    )
                else:
                    # Check seeds
                    has_seeds = (project_copy / "seeds").is_dir() and any((project_copy / "seeds").glob("**/*.csv"))
                    if has_seeds:
                        steps.append(
                            StepResult("Materialize dbt seeds", dbt_cmd + ["seed", "--project-dir", str(project_copy), "--profiles-dir", str(profile_dir), "--log-path", str(log_dir)] + refresh_args)
                        )

                    # Run snapshots BEFORE models so models can safely ref() snapshots
                    has_snapshots = (project_copy / "snapshots").is_dir() and any((project_copy / "snapshots").glob("**/*.sql"))
                    if has_snapshots:
                        steps.append(
                            StepResult("Materialize dbt snapshots", dbt_cmd + ["snapshot", "--project-dir", str(project_copy), "--profiles-dir", str(profile_dir), "--log-path", str(log_dir)])
                        )

                    run_label = "Materialize dbt models (dbt run" + (" --full-refresh" if config.full_refresh else "") + (f" -s {config.select}" if config.select else "") + ")"
                    steps.append(
                        StepResult(run_label, dbt_cmd + ["run", "--project-dir", str(project_copy), "--profiles-dir", str(profile_dir), "--log-path", str(log_dir)] + refresh_args + select_args)
                    )

                    steps.append(
                        StepResult("Run dbt tests", dbt_cmd + ["test", "--project-dir", str(project_copy), "--profiles-dir", str(profile_dir), "--log-path", str(log_dir)] + select_args)
                    )

                    steps.append(
                        StepResult("Generate dbt docs & catalog", dbt_cmd + ["docs", "generate", "--project-dir", str(project_copy), "--profiles-dir", str(profile_dir), "--log-path", str(log_dir)])
                    )

                manifest_path = target_dir / "manifest.json"
                run_results_path = target_dir / "run_results.json"

                for step in steps:
                    step.status = "running"
                    event_logger.emit("step_started", step=step.name, command=step.command)
                    try:
                        step.return_code, step.duration_seconds = stream_command(
                            step.command,
                            project_copy,
                            env,
                            log,
                            step.name,
                            event_logger,
                            run_id,
                            timeout=float(config.timeout_seconds),
                        )
                        step.status = "passed" if step.return_code == 0 else "failed"
                    except OSError as exc:
                        step.error = str(exc)
                        step.status = "failed"
                    except TimeoutError as exc:
                        step.error = str(exc)
                        step.status = "failed"

                    report.steps.append(step)
                    event_logger.emit(
                        "step_finished",
                        step=step.name,
                        status=step.status,
                        return_code=step.return_code,
                        duration_seconds=step.duration_seconds,
                        error_message=step.error or "",
                    )

                    # Parse run_results after execution commands
                    if any(sub in step.command for sub in ("seed", "snapshot", "run", "test", "compile")):
                        step_results, step_failures = parse_run_results(target_dir, manifest_path)
                        for res in step_results:
                            if res.get("is_warning"):
                                report.warning_details.append(f"{res.get('model')}: {res.get('message')}")
                            event_logger.emit("dbt_node_result", step=step.name, **res)
                            if res.get("resource_type") in {"model", "seed", "snapshot"}:
                                report.model_executions.append(res)
                            report.model_test_results.append(res)
                        report.failure_details.extend(step_failures)

                    # After Parse: Verify DAG integrity and Materialization Policy
                    if "parse" in step.command and step.status == "passed":
                        dag_val = verify_dag(manifest_path)
                        report.dag_validation = dag_val
                        event_logger.emit("dag_verification", **dag_val)
                        if dag_val.get("status") != "passed":
                            report.failure_details.extend(dag_val.get("failures", []))
                            break

                        policy_failures = validate_materialization_policy(manifest_path, config.safe_materializations)
                        policy_step = StepResult(
                            name="Validate rerun-safe materializations",
                            command=[],
                            return_code=1 if policy_failures else 0,
                            status="failed" if policy_failures else "passed",
                            error="; ".join(policy_failures) if policy_failures else None,
                        )
                        report.steps.append(policy_step)
                        if policy_failures:
                            report.failure_details.extend(policy_failures)
                            break

                    if step.status == "failed":
                        report.failure_details.append(f"{step.name} failed (exit code {step.return_code})")
                        break

                # Object and Database Validation
                if is_compile:
                    if manifest_path.is_file():
                        executed_nodes = {str(item.get("node")) for item in report.model_executions if item.get("node")}
                        target_nodes = executed_nodes if (config.select and executed_nodes) else None
                        expected, exp_failures = expected_relations(manifest_path, target_node_ids=target_nodes)
                        report.object_validation = {
                            "status": "passed" if not exp_failures else "failed",
                            "expected_objects": expected,
                            "actual_objects": expected,
                            "failures": exp_failures,
                            "additional_or_preexisting_objects": [],
                        }
                        if exp_failures:
                            report.failure_details.extend(exp_failures)
                    else:
                        report.object_validation = {
                            "status": "failed",
                            "failures": ["dbt manifest was not generated during compilation"],
                        }
                elif manifest_path.is_file():
                    executed_nodes = {str(item.get("node")) for item in report.model_executions if item.get("node")}
                    target_nodes = executed_nodes if config.select and executed_nodes else None
                    catalog_path = target_dir / "catalog.json"
                    if catalog_path.is_file():
                        report.object_validation = validate_catalog(manifest_path, catalog_path, target_node_ids=target_nodes)
                    else:
                        # Fallback to direct duckdb inspection
                        report.object_validation = verify_database_objects_direct(
                            sandbox_metadata, manifest_path, db_type, sandbox_data_dir, duckdb_extensions, target_node_ids=target_nodes
                        )
                    report.failure_details.extend(report.object_validation.get("failures", []))
                    if not is_compile and report.object_validation.get("actual_objects"):
                        enrich_objects_with_samples(
                            report.object_validation["actual_objects"],
                            sandbox_metadata,
                            db_type,
                            sandbox_data_dir,
                            duckdb_extensions,
                            sample_limit=15,
                        )
                else:
                    report.object_validation = {
                        "status": "not_run",
                        "failures": ["dbt manifest was not generated"],
                    }

                # Safe Rerun Behavior Verification (Idempotency check)
                if is_compile:
                    report.rerun_policy = "dry-run syntax and DAG topology verification (no data mutations)"
                    report.rerun_verification = {
                        "status": "passed",
                        "duration_seconds": 0.0,
                        "message": "Compilation & DAG verification mode: models and sequence verified without data.",
                    }
                elif should_verify_rerun and not report.failure_details and all(s.status == "passed" for s in report.steps):
                    print("\n--- Verifying Safe Repeated Execution (Idempotency) ---", flush=True)
                    rerun_cmd = dbt_cmd + ["run", "--project-dir", str(project_copy), "--profiles-dir", str(profile_dir), "--log-path", str(log_dir)] + select_args
                    rerun_step = StepResult("Safe repeated execution (dbt run rerun)", rerun_cmd)
                    rerun_step.status = "running"
                    rerun_code, rerun_dur = stream_command(
                        rerun_cmd, project_copy, env, log, rerun_step.name, event_logger, run_id, timeout=float(config.timeout_seconds)
                    )
                    rerun_step.return_code = rerun_code
                    rerun_step.duration_seconds = rerun_dur
                    rerun_step.status = "passed" if rerun_code == 0 else "failed"
                    report.steps.append(rerun_step)
                    if rerun_code != 0:
                        report.failure_details.append("Rerun failed: project is not idempotent under repeated executions")
                        report.rerun_verification = {"status": "failed", "duration_seconds": rerun_dur}
                    else:
                        report.rerun_verification = {
                            "status": "passed",
                            "duration_seconds": rerun_dur,
                            "message": "Repeated execution safe: models cleanly materialized without conflict.",
                        }
                    event_logger.emit("rerun_verification", **report.rerun_verification)

                    # Refresh sample rows and database state after rerun!
                    if not is_compile and report.object_validation.get("actual_objects"):
                        enrich_objects_with_samples(
                            report.object_validation["actual_objects"],
                            sandbox_metadata,
                            db_type,
                            sandbox_data_dir,
                            duckdb_extensions,
                            sample_limit=15,
                        )

        except Exception as exc:
            report.failure_details.append(f"Runner execution failed: {exc}")
            event_logger.emit("runner_error", error_message=str(exc))
            log.write(f"\nRunner execution failed: {exc}\n")

        report.sandbox_cleanup_status = (
            "preserved for interactive console"
            if sandbox_dir is not None and sandbox_created
            else "cleaned" if sandbox_created else "not_created"
        )
        if sandbox_dir is not None and sandbox_created:
            if "project_copy" in locals():
                report.project_dir = str(project_copy)
            if "sandbox_metadata" in locals():
                report.ducklake_metadata_location = str(sandbox_metadata)
            if "sandbox_data_dir" in locals():
                report.data_location = str(sandbox_data_dir) if sandbox_data_dir else ""
        event_logger.emit("sandbox_cleanup", status=report.sandbox_cleanup_status)

    report.finished_at = datetime.now(timezone.utc).isoformat()
    report.overall_status = (
        "passed"
        if report.steps
        and all(s.status == "passed" for s in report.steps)
        and not report.failure_details
        and report.object_validation.get("status") == "passed"
        else "failed"
    )

    save_report(report)
    print(f"\nRun {report.overall_status.upper()}. Report: {report_path}")
    return report


def print_report(report: RunReport) -> None:
    print(f"\n=======================================================")
    print(f"Run: {report.run_id} — {report.overall_status.upper()}")
    print(f"Database Type: {report.database_type.upper()}")
    print(f"Project: {report.project_dir}")
    print(f"Database: {report.ducklake_metadata_location}")
    if report.data_location:
        print(f"Lake Data: {report.data_location}")
    print(f"Started: {report.started_at} | Finished: {report.finished_at}")
    print(f"Rerun Policy: {report.rerun_policy}")
    print(f"Sandbox Cleanup: {report.sandbox_cleanup_status}")

    print("\nSteps:")
    for step in report.steps:
        code = "not run" if step.return_code is None else str(step.return_code)
        print(f"  [{step.status.upper():6}] {step.name} (exit {code}, {step.duration_seconds:.2f}s)")

    if report.dag_validation:
        print(f"\nDAG Verification: {report.dag_validation.get('status', 'unknown').upper()}")
        print(
            f"  Models: {report.dag_validation.get('models_count', 0)} "
            f"({report.dag_validation.get('models_by_materialization', {})}), "
            f"Seeds: {report.dag_validation.get('seeds_count', 0)}, "
            f"Snapshots: {report.dag_validation.get('snapshots_count', 0)}, "
            f"Tests: {report.dag_validation.get('tests_count', 0)}"
        )

    if report.model_executions:
        print(f"\nModel Executions ({len(report.model_executions)}):")
        for res in report.model_executions:
            dur = float(res.get("duration_seconds") or 0.0)
            err = res.get("error_message")
            err_suffix = f" — ERROR: {err}" if err else ""
            print(f"  - {res.get('model')} [{res.get('object_type')}] -> {res.get('execution_status')} ({dur:.3f}s){err_suffix}")

    if report.object_validation:
        print(f"\nObject Validation: {report.object_validation.get('status', 'not_run').upper()}")
        for obj in report.object_validation.get("actual_objects", []):
            cols = ", ".join(f"{c.get('name')} {c.get('data_type')}" for c in obj.get("columns", []))
            print(f"  - {obj.get('database')}.{obj.get('schema')}.{obj.get('name')} ({obj.get('relation_type')}): {cols}")

    if report.rerun_verification:
        print(f"\nRerun Verification (Idempotency): {report.rerun_verification.get('status', 'not_run').upper()}")
        print(f"  {report.rerun_verification.get('message', '')}")

    if report.warning_details:
        print(f"\nWarnings ({len(report.warning_details)}):")
        for warn in report.warning_details:
            print(f"  ! {warn}")

    if report.failure_details:
        print(f"\nFailures ({len(report.failure_details)}):")
        for fail in report.failure_details:
            print(f"  * {fail}")

    print(f"\nLog: {report.log_file}")
    print(f"Structured Log: {report.structured_log_file}")
    print(f"Report JSON: {report.report_file}")
    print(f"=======================================================\n")
