from __future__ import annotations

import json
from pathlib import Path
import duckdb
import pytest

from dbt_runner.config import RunnerConfig
from dbt_runner.runner import run_project


def _create_minimal_dbt_project(
    base_dir: Path,
    project_name: str = "test_pipeline_proj",
    has_seed: bool = True,
    use_source: bool = False,
    source_database: str = "ducklake",
    source_schema: str = "main",
) -> Path:
    proj_dir = base_dir / project_name
    proj_dir.mkdir(parents=True, exist_ok=True)
    models_dir = proj_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    dbt_proj_yml = [
        f"name: '{project_name}'",
        "version: '1.0.0'",
        "config-version: 2",
        "profile: 'default'",
        "model-paths: ['models']",
        "seed-paths: ['seeds']",
        "snapshot-paths: ['snapshots']",
        "target-path: 'target'",
        "clean-targets: ['target']",
        "",
        "models:",
        f"  {project_name}:",
        "    +materialized: table",
    ]
    (proj_dir / "dbt_project.yml").write_text("\n".join(dbt_proj_yml), encoding="utf-8")

    if has_seed:
        seeds_dir = proj_dir / "seeds"
        seeds_dir.mkdir(parents=True, exist_ok=True)
        (seeds_dir / "sample_seed.csv").write_text("id,name\n1,alice\n2,bob\n", encoding="utf-8")
        (models_dir / "my_model.sql").write_text(
            "SELECT id, name FROM {{ ref('sample_seed') }}",
            encoding="utf-8",
        )
    elif use_source:
        (models_dir / "source.yml").write_text(
            f"version: 2\nsources:\n  - name: my_source\n    database: {source_database}\n    schema: {source_schema}\n    tables:\n      - name: ext_orders\n",
            encoding="utf-8",
        )
        (models_dir / "my_model.sql").write_text(
            "SELECT id, amount FROM {{ source('my_source', 'ext_orders') }}",
            encoding="utf-8",
        )
    else:
        # Empty seeds dir with gitkeep
        seeds_dir = proj_dir / "seeds"
        seeds_dir.mkdir(parents=True, exist_ok=True)
        (seeds_dir / ".gitkeep").touch()
        (models_dir / "my_model.sql").write_text(
            "SELECT 1 AS id, 'direct' AS name",
            encoding="utf-8",
        )

    return proj_dir


def test_pipeline_project_with_seeds(tmp_path: Path) -> None:
    proj_dir = _create_minimal_dbt_project(tmp_path, "proj_with_seeds", has_seed=True)
    db_file = tmp_path / "test_seeds.duckdb"
    duckdb.connect(str(db_file)).close()
    log_dir = tmp_path / "run_logs"

    cfg = RunnerConfig(
        dbt_package="dbt-duckdb",
        run_logs_dir=log_dir,
        safe_materializations=("table", "view"),
        config_path=tmp_path / "config.json",
        verify_rerun=False,
    )

    report = run_project(
        project=proj_dir,
        database_or_data=db_file,
        config=cfg,
    )

    assert report.overall_status == "passed"
    step_names = [s.name for s in report.steps]
    assert "Materialize dbt seeds" in step_names
    assert report.pipeline_stages[2].status == "passed"
    assert any("Materialize dbt models" in name for name in step_names)


def test_pipeline_project_without_seeds_preexisting_table(tmp_path: Path) -> None:
    # Project with no seeds, relying on pre-existing source table
    proj_dir = _create_minimal_dbt_project(
        tmp_path,
        "proj_no_seeds",
        has_seed=False,
        use_source=True,
        source_database="ducklake",
        source_schema="main",
    )
    db_file = tmp_path / "test_preexisting.duckdb"

    # Pre-populate table in the database before dbt runs
    conn = duckdb.connect(str(db_file))
    conn.execute("CREATE TABLE ext_orders (id INT, amount DOUBLE)")
    conn.execute("INSERT INTO ext_orders VALUES (1, 99.5), (2, 149.0)")
    conn.close()

    log_dir = tmp_path / "run_logs"
    cfg = RunnerConfig(
        dbt_package="dbt-duckdb",
        run_logs_dir=log_dir,
        safe_materializations=("table", "view"),
        config_path=tmp_path / "config.json",
        verify_rerun=False,
        target_database="ducklake",
    )

    report = run_project(
        project=proj_dir,
        database_or_data=db_file,
        config=cfg,
    )

    assert report.overall_status == "passed"
    step_names = [s.name for s in report.steps]
    assert any(s.name == "Load dbt seeds" and s.status == "skipped" for s in report.steps)
    assert report.pipeline_stages[2].status == "passed"
    assert any("Materialize dbt models" in name for name in step_names)


def test_pipeline_catalog_mismatch_aborts_actionably(tmp_path: Path) -> None:
    # Project referencing snowflake-specific 'raw' catalog that is not attached
    proj_dir = _create_minimal_dbt_project(
        tmp_path,
        "proj_catalog_mismatch",
        has_seed=False,
        use_source=True,
        source_database="raw",
        source_schema="jaffle_shop",
    )
    db_file = tmp_path / "test_mismatch.duckdb"
    duckdb.connect(str(db_file)).close()
    log_dir = tmp_path / "run_logs"

    cfg = RunnerConfig(
        dbt_package="dbt-duckdb",
        run_logs_dir=log_dir,
        safe_materializations=("table", "view"),
        config_path=tmp_path / "config.json",
        verify_rerun=False,
        target_database="ducklake",
    )

    report = run_project(
        project=proj_dir,
        database_or_data=db_file,
        config=cfg,
    )

    assert report.overall_status == "needs_configuration"
    assert report.pipeline_stages[2].status == "needs_configuration"
    failures = " ".join(report.failure_details)
    assert "MissingSourceData" in failures
    assert any(d.category == "MissingSourceData" for d in report.diagnostics)
    # Ensure dbt run was NOT executed following prerequisite failure
    assert not any("Materialize dbt models" in s.name for s in report.steps)
    log_content = Path(report.log_file).read_text(encoding="utf-8")
    assert "MissingSourceData" in log_content


def test_pipeline_compile_only(tmp_path: Path) -> None:
    proj_dir = _create_minimal_dbt_project(tmp_path, "proj_compile", has_seed=False, use_source=False)
    db_file = tmp_path / "test_compile.duckdb"
    duckdb.connect(str(db_file)).close()
    log_dir = tmp_path / "run_logs"

    cfg = RunnerConfig(
        dbt_package="dbt-duckdb",
        run_logs_dir=log_dir,
        safe_materializations=("table", "view"),
        config_path=tmp_path / "config.json",
        verify_rerun=False,
        compile_only=True,
    )

    report = run_project(
        project=proj_dir,
        database_or_data=db_file,
        config=cfg,
    )

    assert report.overall_status == "passed"
    step_names = [s.name for s in report.steps]
    assert any("Compile dbt models" in name for name in step_names)
    assert not any("Materialize dbt models" in name for name in step_names)


def test_pipeline_full_refresh_flag_passed(tmp_path: Path) -> None:
    proj_dir = _create_minimal_dbt_project(tmp_path, "proj_full_refresh", has_seed=True)
    db_file = tmp_path / "test_full_refresh.duckdb"
    duckdb.connect(str(db_file)).close()
    log_dir = tmp_path / "run_logs"

    cfg = RunnerConfig(
        dbt_package="dbt-duckdb",
        run_logs_dir=log_dir,
        safe_materializations=("table", "view"),
        config_path=tmp_path / "config.json",
        verify_rerun=False,
        full_refresh=True,
    )

    report = run_project(
        project=proj_dir,
        database_or_data=db_file,
        config=cfg,
    )

    assert report.overall_status == "passed"
    seed_steps = [s for s in report.steps if s.name == "Materialize dbt seeds"]
    assert len(seed_steps) == 1
    assert "--full-refresh" in seed_steps[0].command

    run_steps = [s for s in report.steps if "Materialize dbt models" in s.name]
    assert len(run_steps) == 1
    assert "--full-refresh" in run_steps[0].command


def test_pipeline_compile_only_with_missing_source_tables_requests_configuration(tmp_path: Path) -> None:
    # Required source relations are validated before compile mode can proceed.
    proj_dir = _create_minimal_dbt_project(
        tmp_path,
        "proj_compile_missing_sources",
        has_seed=False,
        use_source=True,
        source_database="ducklake",
        source_schema="main",
    )
    db_file = tmp_path / "test_compile_empty.duckdb"
    duckdb.connect(str(db_file)).close()
    log_dir = tmp_path / "run_logs"

    cfg = RunnerConfig(
        dbt_package="dbt-duckdb",
        run_logs_dir=log_dir,
        safe_materializations=("table", "view"),
        config_path=tmp_path / "config.json",
        verify_rerun=False,
        compile_only=True,
        target_database="ducklake",
    )

    report = run_project(
        project=proj_dir,
        database_or_data=db_file,
        config=cfg,
    )

    assert report.overall_status == "needs_configuration"
    assert report.pipeline_stages[2].status == "needs_configuration"
    assert not any("Compile dbt models" in s.name for s in report.steps)


def test_pipeline_seeds_with_different_source_schema_reports_mismatch(tmp_path: Path) -> None:
    # Project seeds loaded into the target schema must not be silently bridged to source schema.
    proj_dir = tmp_path / "proj_seed_schema_bridge"
    proj_dir.mkdir(parents=True, exist_ok=True)
    models_dir = proj_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    seeds_dir = proj_dir / "seeds"
    seeds_dir.mkdir(parents=True, exist_ok=True)

    dbt_proj_yml = [
        "name: 'proj_seed_schema_bridge'",
        "version: '1.0.0'",
        "config-version: 2",
        "profile: 'default'",
        "model-paths: ['models']",
        "seed-paths: ['seeds']",
        "target-path: 'target'",
        "clean-targets: ['target']",
        "",
        "models:",
        "  proj_seed_schema_bridge:",
        "    +materialized: table",
    ]
    (proj_dir / "dbt_project.yml").write_text("\n".join(dbt_proj_yml), encoding="utf-8")

    # Seed file in seeds/
    (seeds_dir / "raw_customers.csv").write_text("id,name\n1,alice\n2,bob\n", encoding="utf-8")

    # Source expecting schema 'raw'
    (models_dir / "source.yml").write_text(
        "version: 2\nsources:\n  - name: raw\n    schema: raw\n    tables:\n      - name: raw_customers\n",
        encoding="utf-8",
    )
    (models_dir / "stg_customers.sql").write_text(
        "SELECT id, name FROM {{ source('raw', 'raw_customers') }}",
        encoding="utf-8",
    )

    db_file = tmp_path / "test_bridge.duckdb"
    duckdb.connect(str(db_file)).close()
    log_dir = tmp_path / "run_logs"

    cfg = RunnerConfig(
        dbt_package="dbt-duckdb",
        run_logs_dir=log_dir,
        safe_materializations=("table", "view"),
        config_path=tmp_path / "config.json",
        verify_rerun=False,
    )

    report = run_project(
        project=proj_dir,
        database_or_data=db_file,
        config=cfg,
    )

    assert report.overall_status == "needs_configuration"
    step_names = [s.name for s in report.steps]
    assert "Materialize dbt seeds" in step_names
    assert not any("Materialize dbt models" in name for name in step_names)
    assert any(d.category == "LocationMismatch" for d in report.diagnostics)
    assert (proj_dir / "dbt_project.yml").read_text(encoding="utf-8") == "\n".join(dbt_proj_yml)

