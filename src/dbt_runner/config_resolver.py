from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .discovery import ProjectManifest
from .project import write_profile
from .relations import AdapterRegistry


@dataclass
class ResolvedTarget:
    status: str
    profile_name: str
    target_name: str
    adapter_type: str
    adapter_package: str
    database: str | None
    schema: str | None
    details: dict[str, Any] = field(default_factory=dict)
    remediation: dict[str, Any] | None = None


class ConfigResolver:
    """Resolve project target settings and create a run-scoped DuckDB profile."""

    def resolve(
        self,
        project: ProjectManifest,
        config: Any,
        database_file: Path,
        data_dir: Path | None,
        profiles_dir: Path,
        extension_dir: Path,
        db_type: str,
    ) -> ResolvedTarget:
        profile_name = project.profile
        if not profile_name:
            return ResolvedTarget("needs_configuration", "", "", "", "", None, None,
                remediation={"action": "set_profile", "message": "Declare a profile name in dbt_project.yml."})

        bundled_profile = project.bundled_profiles.get(profile_name, {})
        target_name = str(bundled_profile.get("target") or "") if isinstance(bundled_profile, dict) else ""
        outputs = bundled_profile.get("outputs", {}) if isinstance(bundled_profile, dict) else {}
        target = outputs.get(target_name, {}) if isinstance(outputs, dict) else {}
        if not target and isinstance(outputs, dict) and len(outputs) == 1:
            target_name, target = next(iter(outputs.items()))
        target = target if isinstance(target, dict) else {}

        adapter_type = str(target.get("type") or config.adapter_type or ("duckdb" if db_type in {"duckdb", "ducklake"} else "")).strip().lower()
        adapter_package = str(config.dbt_package or f"dbt-{adapter_type}").strip()
        schema = config.target_schema or target.get("schema")
        database = config.target_database or target.get("database")
        if not database:
            database = database_file.stem

        if not AdapterRegistry().supports(adapter_type):
            return ResolvedTarget(
                "needs_configuration", profile_name, target_name, adapter_type, adapter_package,
                str(database) if database else None, str(schema) if schema else None,
                remediation={"action": "install_adapter_plugin", "message": f"Adapter '{adapter_type}' needs a registered execution and catalog plugin."},
            )
        if not schema:
            # Resolve the target engine's active schema from a live connection instead of
            # encoding an adapter-specific default in the runner.
            try:
                import duckdb
                conn = duckdb.connect(str(database_file), read_only=True)
                try:
                    schema = str(conn.execute("SELECT current_schema()").fetchone()[0])
                finally:
                    conn.close()
            except Exception:
                try:
                    import duckdb
                    conn = duckdb.connect(":memory:")
                    try:
                        schema = str(conn.execute("SELECT current_schema()").fetchone()[0])
                    finally:
                        conn.close()
                except Exception:
                    schema = None
        if not schema:
            return ResolvedTarget(
                "needs_configuration", profile_name, target_name, adapter_type, adapter_package,
                str(database) if database else None, None,
                remediation={"action": "set_target_schema", "message": "Set the target schema in the project profile or run settings."},
            )

        # Secrets in the project's profile are never copied into the run-scoped profile.
        write_profile(
            profiles_dir / "profiles.yml", profile_name, data_dir, database_file,
            extension_dir, db_type=db_type, default_schema=str(schema),
            target_database=str(database) if database else None,
            attachments=config.attachments, catalog_mappings=config.catalog_mappings_dict,
        )
        effective = {
            "profile": profile_name, "target": target_name or "runner", "type": adapter_type,
            "database": database, "schema": schema,
        }
        return ResolvedTarget("passed", profile_name, target_name or "runner", adapter_type,
            adapter_package, str(database) if database else None, str(schema), effective)


def redact_secrets(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [redact_secrets(item, secrets) for item in value]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            if any(label in str(key).casefold() for label in ("password", "token", "secret", "credential")):
                safe[key] = "[REDACTED]"
            else:
                safe[key] = redact_secrets(item, secrets)
        return safe
    return value
