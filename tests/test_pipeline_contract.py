from __future__ import annotations

import json
from pathlib import Path

import duckdb

from dbt_runner.config import RunnerConfig
from dbt_runner.discovery import ProjectInspector
from dbt_runner.preparation import DataPrepManager, DbtSeedProvider, SqlInitScriptProvider
from dbt_runner.relations import RelationValidator
from dbt_runner.runner import run_project


def _project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "dbt_project.yml").write_text(
        "name: sample\nversion: '1.0'\nconfig-version: 2\nprofile: sample_profile\n",
        encoding="utf-8",
    )
    models = root / "models"
    models.mkdir(parents=True)
    return root


def test_project_without_optional_directories_has_skipped_seed_status(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    manifest = ProjectInspector().inspect(project)

    assert manifest.resources["seeds"]["present"] is False
    seed_result = DbtSeedProvider().prepare(manifest, {})
    assert seed_result.status == "skipped"
    assert "no seed CSV files" in seed_result.summary
    assert manifest.resources["snapshots"]["present"] is False
    assert manifest.resources["macros"]["present"] is False


def test_run_without_seed_directory_reports_seed_skipped_and_passes(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    (project / "models" / "one.sql").write_text("select 1 as id", encoding="utf-8")
    database = tmp_path / "target.duckdb"
    duckdb.connect(str(database)).close()
    config = RunnerConfig(
        dbt_package="dbt-duckdb", run_logs_dir=tmp_path / "logs",
        safe_materializations=("table", "view"), config_path=tmp_path / "runner.json",
        verify_rerun=False,
    )

    report = run_project(project, database, config=config)

    assert report.overall_status == "passed"
    skipped_seed = next(step for step in report.steps if step.name == "Load dbt seeds")
    assert skipped_seed.status == "skipped"
    assert report.pipeline_stages[2].status == "passed"


def test_relation_validator_reports_schema_mismatch_without_mutating_project(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    before = (project / "dbt_project.yml").read_bytes()
    database = tmp_path / "warehouse.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute("CREATE SCHEMA staging")
    connection.execute("CREATE TABLE staging.orders (id INTEGER)")
    connection.close()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "nodes": {"model.sample.stg_orders": {"resource_type": "model"}},
        "sources": {"source.sample.raw.orders": {
            "name": "orders", "identifier": "orders", "database": "warehouse", "schema": "raw",
        }},
        "parent_map": {"model.sample.stg_orders": ["source.sample.raw.orders"]},
    }), encoding="utf-8")

    result = RelationValidator().validate(manifest_path, database, "duckdb", primary_database="warehouse")

    assert result["status"] == "failed"
    assert result["missing"] == []
    assert result["mismatches"][0]["expected"] == "warehouse.raw.orders"
    assert result["mismatches"][0]["actual"] == [{
        "database": "warehouse", "schema": "staging", "identifier": "orders",
    }]
    assert (project / "dbt_project.yml").read_bytes() == before


def test_candidate_csv_and_unapproved_sql_require_configuration(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    (project / "data").mkdir()
    (project / "data" / "customers.csv").write_text("id\n1\n", encoding="utf-8")
    (project / "setup").mkdir()
    (project / "setup" / "01_init.sql").write_text("CREATE TABLE marker (id INTEGER);", encoding="utf-8")
    manifest = ProjectInspector().inspect(project)

    results = DataPrepManager().inspect(manifest, {})

    assert results[2].status == "needs_configuration"
    assert results[3].status == "needs_configuration"
    database = tmp_path / "target.duckdb"
    connection = duckdb.connect(str(database))
    tables = connection.execute("SHOW TABLES").fetchall()
    connection.close()
    assert tables == []


def test_approved_setup_sql_with_dbt_jinja_is_blocked_before_raw_execution(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    setup = project / "setup"
    setup.mkdir()
    script = setup / "prepare.sql"
    script.write_text("select * from {{ source('stripe', 'payment') }}", encoding="utf-8")
    manifest = ProjectInspector().inspect(project)

    result = SqlInitScriptProvider().prepare(manifest, {
        "approved_sql_scripts": ["setup/prepare.sql"],
        "sql_target_compatibility": "duckdb",
        "adapter_type": "duckdb",
    })

    assert result.status == "needs_configuration"
    assert result.details["templated_scripts"] == ["setup/prepare.sql"]
    assert "configured model path" in result.remediation.message
