from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .discovery import ProjectManifest
from .models import PipelineStage, Remediation


@dataclass
class PreparationResult:
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    remediation: Remediation | None = None


class SourcePreparationProvider(Protocol):
    name: str

    def prepare(self, project: ProjectManifest, context: dict[str, Any]) -> PreparationResult: ...


class DbtSeedProvider:
    name = "dbt_seed"

    def prepare(self, project: ProjectManifest, context: dict[str, Any]) -> PreparationResult:
        files = [
            relative
            for relative in project.resources.get("seeds", {}).get("files", [])
            if Path(relative).suffix.casefold() == ".csv"
        ]
        if files:
            return PreparationResult("pending", "dbt seed will load configured CSV seeds", {"seed_files": files})
        return PreparationResult("skipped", "Seed step skipped — no seed CSV files found", {"seed_files": []})


class ExistingTableProvider:
    name = "existing_tables"

    def prepare(self, project: ProjectManifest, context: dict[str, Any]) -> PreparationResult:
        return PreparationResult("pending", "Existing source relations will be checked against the target catalog", {
            "declared_sources": project.declared_sources,
        })


class ExternalFileMappingProvider:
    name = "external_file_mapping"

    def prepare(self, project: ProjectManifest, context: dict[str, Any]) -> PreparationResult:
        candidates = [item for item in project.candidate_inputs if item["kind"] == "external_file"]
        mappings = context.get("file_mappings") or {}
        unmapped = [item for item in candidates if item["path"] not in mappings]
        if unmapped:
            return PreparationResult(
                "needs_configuration",
                "Candidate data files need explicit target mappings before loading",
                {"candidate_files": candidates, "unmapped_files": unmapped},
                Remediation("map_external_files", "Choose the target catalog, schema, and table for each candidate file."),
            )
        if candidates and not context.get("apply_file_mappings"):
            loaded = _load_external_files(project, mappings, context)
            return PreparationResult("passed", "Explicitly mapped external files loaded into the isolated target", {
                "candidate_files": candidates, "mappings": mappings, "loaded_files": loaded,
            })
        return PreparationResult("passed" if candidates else "skipped", "External file mappings applied", {
            "candidate_files": candidates, "mappings": mappings,
        })


class SqlInitScriptProvider:
    name = "sql_init_scripts"

    def prepare(self, project: ProjectManifest, context: dict[str, Any]) -> PreparationResult:
        scripts = [item["path"] for item in project.candidate_inputs if item["kind"] == "sql_setup"]
        approved = context.get("approved_sql_scripts") or []
        if scripts and set(scripts) != set(approved):
            return PreparationResult(
                "needs_configuration",
                "Setup SQL scripts require an explicit execution policy",
                {"candidate_scripts": scripts, "approved_scripts": approved},
                Remediation("approve_sql_scripts", "Select scripts, their execution order, and compatible target."),
            )
        if scripts:
            compatibility = context.get("sql_target_compatibility")
            if compatibility != context.get("adapter_type"):
                return PreparationResult("needs_configuration", "Approved SQL policy must declare the active target compatibility", {
                    "candidate_scripts": scripts, "approved_scripts": approved,
                    "target_compatibility": compatibility,
                }, Remediation("configure_sql_execution", "Confirm that the approved setup scripts are compatible with the active target."))
            templated = _scripts_with_dbt_jinja(project, approved)
            if templated:
                return PreparationResult(
                    "needs_configuration",
                    "Approved setup SQL contains dbt Jinja and cannot run as raw target SQL",
                    {"templated_scripts": templated},
                    Remediation(
                        "move_templated_sql_into_model_paths",
                        "Move dbt-templated SQL into a configured model path so dbt can render ref() and source() before execution.",
                    ),
                )
            executed = _execute_approved_sql(project, approved, context)
            return PreparationResult("passed", "Approved setup SQL scripts executed in the isolated run target", {
                "candidate_scripts": scripts, "approved_scripts": executed,
            })
        return PreparationResult("skipped", "Setup SQL step skipped — no candidate scripts found", {"candidate_scripts": []})


class ExternalWarehouseProvider:
    name = "external_warehouse"

    def prepare(self, project: ProjectManifest, context: dict[str, Any]) -> PreparationResult:
        if context.get("external_warehouse_required") and not context.get("credentials_configured"):
            return PreparationResult(
                "needs_configuration", "External warehouse credentials are required",
                {"credential_profile": context.get("credential_profile")},
                Remediation("configure_credentials", "Configure a credential profile or secret environment variables."),
            )
        return PreparationResult("skipped", "No external warehouse credential request was declared", {})


class MissingSourceHandler:
    def handle(self, missing: list[dict[str, Any]]) -> PreparationResult:
        relations = [item.get("expected") for item in missing]
        return PreparationResult(
            "needs_configuration", "Required source relations are missing from the target",
            {"missing_relations": relations},
            Remediation("supply_source_data", "Provide each listed source relation, then resume from source preparation."),
        )


class DataPrepManager:
    def __init__(self, providers: list[SourcePreparationProvider] | None = None) -> None:
        self.providers = providers or [
            DbtSeedProvider(), ExistingTableProvider(), ExternalFileMappingProvider(),
            SqlInitScriptProvider(), ExternalWarehouseProvider(),
        ]

    def inspect(self, project: ProjectManifest, context: dict[str, Any] | None = None) -> list[PreparationResult]:
        values = context or {}
        return [provider.prepare(project, values) for provider in self.providers]

    def apply_results(self, stage: PipelineStage, results: list[PreparationResult]) -> None:
        stage.details["providers"] = [
            {"name": provider.name, **result.__dict__}
            for provider, result in zip(self.providers, results)
        ]
        blocked = next((result for result in results if result.status == "needs_configuration"), None)
        if blocked:
            stage.status, stage.summary, stage.remediation = blocked.status, blocked.summary, blocked.remediation
        elif all(result.status == "skipped" for result in results):
            stage.status, stage.summary = "skipped", "No source data preparation was required"
        else:
            stage.status = "running"
            stage.summary = "Source preparation requirements identified; validating target relations"


def _identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("Target relation identifiers must be non-empty")
    return '"' + value.replace('"', '""') + '"'


def _scripts_with_dbt_jinja(project: ProjectManifest, scripts: list[str]) -> list[str]:
    """Reject dbt-templated SQL at the raw SQL execution boundary.

    This is a syntax-boundary check only; dbt remains responsible for parsing Jinja,
    resolving refs/sources, and compiling model SQL.
    """
    root = Path(project.project_dir).resolve()
    templated: list[str] = []
    for relative in scripts:
        path = (root / relative).resolve(strict=True)
        if root not in path.parents or path.suffix.casefold() != ".sql":
            raise ValueError(f"Approved SQL path is outside the project or not SQL: {relative}")
        contents = path.read_text(encoding="utf-8")
        if "{{" in contents or "{%" in contents or "{#" in contents:
            templated.append(relative)
    return templated


def _load_external_files(project: ProjectManifest, mappings: dict[str, Any], context: dict[str, Any]) -> list[str]:
    import duckdb

    root = Path(project.project_dir).resolve()
    db_file = Path(context["database_file"]).resolve()
    db_type = str(context.get("db_type"))
    target_database = str(context.get("target_database") or db_file.stem)
    data_dir = context.get("data_dir")
    conn = duckdb.connect(":memory:")
    loaded: list[str] = []
    try:
        if db_type == "ducklake" and data_dir:
            conn.execute("LOAD ducklake")
            escaped_data = str(data_dir).replace("'", "''")
            escaped_meta = str(db_file).replace("'", "''")
            conn.execute(f"ATTACH 'ducklake:{escaped_meta}' AS {_identifier(target_database)} (DATA_PATH '{escaped_data}', OVERRIDE_DATA_PATH TRUE)")
        else:
            escaped = str(db_file).replace("'", "''")
            conn.execute(f"ATTACH '{escaped}' AS {_identifier(target_database)}")
        for relative, mapping in mappings.items():
            path = (root / relative).resolve(strict=True)
            if root not in path.parents or not isinstance(mapping, dict):
                raise ValueError(f"Invalid external file mapping: {relative}")
            database = str(mapping.get("database") or "")
            schema = str(mapping.get("schema") or "")
            table = str(mapping.get("table") or "")
            if not database or not schema or not table:
                raise ValueError(f"External mapping for {relative} must include database, schema, and table")
            if database.casefold() != target_database.casefold():
                raise ValueError(f"External mapping for {relative} targets unattached database {database}")
            escaped_path = str(path).replace("'", "''")
            if path.suffix.casefold() == ".csv":
                reader = f"read_csv_auto('{escaped_path}', header=true)"
            elif path.suffix.casefold() == ".parquet":
                reader = f"read_parquet('{escaped_path}')"
            elif path.suffix.casefold() in {".json", ".ndjson"}:
                reader = f"read_json_auto('{escaped_path}')"
            else:
                raise ValueError(f"Unsupported mapped input format: {path.suffix}")
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_identifier(database)}.{_identifier(schema)}")
            conn.execute(
                f"CREATE OR REPLACE TABLE {_identifier(database)}.{_identifier(schema)}.{_identifier(table)} AS SELECT * FROM {reader}"
            )
            loaded.append(relative)
    finally:
        conn.close()
    return loaded


def _execute_approved_sql(project: ProjectManifest, scripts: list[str], context: dict[str, Any]) -> list[str]:
    import duckdb

    root = Path(project.project_dir).resolve()
    db_file = Path(context["database_file"]).resolve()
    data_dir = context.get("data_dir")
    db_type = str(context.get("db_type"))
    database = str(context.get("target_database") or db_file.stem)
    conn = duckdb.connect(":memory:")
    executed: list[str] = []
    try:
        if db_type == "ducklake" and data_dir:
            conn.execute("LOAD ducklake")
            escaped_data = str(data_dir).replace("'", "''")
            escaped_meta = str(db_file).replace("'", "''")
            conn.execute(f"ATTACH 'ducklake:{escaped_meta}' AS {_identifier(database)} (DATA_PATH '{escaped_data}', OVERRIDE_DATA_PATH TRUE)")
        else:
            escaped = str(db_file).replace("'", "''")
            conn.execute(f"ATTACH '{escaped}' AS {_identifier(database)}")
        for relative in scripts:
            path = (root / relative).resolve(strict=True)
            if root not in path.parents or path.suffix.casefold() != ".sql":
                raise ValueError(f"Approved SQL path is outside the project or not SQL: {relative}")
            conn.execute(path.read_text(encoding="utf-8"))
            executed.append(relative)
    finally:
        conn.close()
    return executed
