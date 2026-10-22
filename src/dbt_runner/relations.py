from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


class DuckDbAdapter:
    adapter_types = {"duckdb", "ducklake"}

    def list_relations(
        self,
        database_file: Path,
        db_type: str,
        data_dir: Path | None = None,
        primary_database: str | None = None,
        attachments: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> set[tuple[str, str, str]]:
        import duckdb

        primary = primary_database or database_file.stem
        conn = duckdb.connect(":memory:")
        try:
            if db_type == "ducklake" and data_dir and data_dir.is_dir():
                conn.execute("LOAD ducklake")
                conn.execute(
                    f"ATTACH 'ducklake:{database_file}' AS {_q(primary)} "
                    f"(DATA_PATH '{str(data_dir).replace(chr(39), chr(39) * 2)}', OVERRIDE_DATA_PATH TRUE, READ_ONLY TRUE)"
                )
            elif database_file.is_file() and database_file.stat().st_size:
                path = str(database_file).replace("'", "''")
                conn.execute(f"ATTACH '{path}' AS {_q(primary)} (READ_ONLY)")
            for attachment in attachments:
                alias = str(attachment.get("alias") or "").strip()
                path = str(attachment.get("path") or "").replace("'", "''")
                if alias and alias.casefold() != primary.casefold():
                    conn.execute(f"ATTACH '{path}' AS {_q(alias)} (READ_ONLY)")
            rows = conn.execute(
                "SELECT table_catalog, table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema', 'pg_catalog')"
            ).fetchall()
            return {(str(db).casefold(), str(schema).casefold(), str(name).casefold()) for db, schema, name in rows}
        finally:
            conn.close()


class AdapterPlugin(Protocol):
    adapter_types: set[str]

    def list_relations(
        self,
        database_file: Path,
        db_type: str,
        data_dir: Path | None = None,
        primary_database: str | None = None,
        attachments: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> set[tuple[str, str, str]]: ...


class AdapterRegistry:
    def __init__(self, plugins: list[AdapterPlugin] | None = None) -> None:
        self._plugins = plugins or [DuckDbAdapter()]

    def supports(self, adapter_type: str) -> bool:
        return any(adapter_type.casefold() in plugin.adapter_types for plugin in self._plugins)

    def get(self, adapter_type: str) -> AdapterPlugin | None:
        return next((plugin for plugin in self._plugins if adapter_type.casefold() in plugin.adapter_types), None)


class RelationValidator:
    """Validate exact source locations from dbt's manifest using adapter catalog metadata."""

    def __init__(self, adapter: AdapterPlugin | None = None) -> None:
        self.adapter = adapter or AdapterRegistry().get("duckdb") or DuckDbAdapter()

    def validate(
        self,
        manifest_path: Path,
        database_file: Path,
        db_type: str,
        data_dir: Path | None = None,
        primary_database: str | None = None,
        attachments: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]:
        if not manifest_path.is_file():
            return {"status": "failed", "valid": [], "missing": [], "mismatches": [], "failures": ["dbt manifest.json was not generated"]}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"status": "failed", "valid": [], "missing": [], "mismatches": [], "failures": [f"Could not read dbt manifest: {exc}"]}

        used: set[str] = set()
        for parents in manifest.get("parent_map", {}).values():
            used.update(parent for parent in parents if str(parent).startswith("source."))
        sources = manifest.get("sources", {})
        expected = []
        for unique_id, source in sources.items():
            if unique_id not in used:
                continue
            identifier = str(source.get("identifier") or source.get("name") or "").strip()
            schema = str(source.get("schema") or "").strip()
            database = str(source.get("database") or primary_database or database_file.stem).strip()
            if identifier and schema:
                expected.append({"unique_id": unique_id, "database": database, "schema": schema, "identifier": identifier})

        try:
            actual = self.adapter.list_relations(database_file, db_type, data_dir, primary_database, attachments)
        except Exception as exc:
            return {"status": "failed", "valid": [], "missing": [], "mismatches": [], "failures": [f"Target catalog inspection failed: {exc}"]}

        valid: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        mismatches: list[dict[str, Any]] = []
        for relation in expected:
            key = tuple(relation[k].casefold() for k in ("database", "schema", "identifier"))
            if key in actual:
                valid.append(relation)
                continue
            locations = [
                {"database": database, "schema": schema, "identifier": identifier}
                for database, schema, identifier in actual
                if identifier == key[2]
            ]
            record = {"expected": f"{relation['database']}.{relation['schema']}.{relation['identifier']}", "actual": locations}
            if locations:
                mismatches.append(record)
            else:
                missing.append(record)

        failures = [
            f"LocationMismatch: expected {item['expected']}; found " + ", ".join(
                f"{loc['database']}.{loc['schema']}.{loc['identifier']}" for loc in item["actual"]
            ) for item in mismatches
        ] + [f"MissingSourceData: required relation {item['expected']} does not exist" for item in missing]
        return {
            "status": "passed" if not failures else "failed",
            "valid": valid,
            "missing": missing,
            "mismatches": mismatches,
            "failures": failures,
        }
