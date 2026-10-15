from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def expected_relations(
    manifest_path: Path,
    target_node_ids: set[str] | None = None,
) -> tuple[list[dict[str, object]], list[str]]:
    """Read physical relations and declared column contracts from dbt's DAG."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"Could not read dbt manifest: {exc}"]

    expected: list[dict[str, object]] = []
    failures: list[str] = []
    nodes = manifest.get("nodes", {})
    for unique_id, node in nodes.items():
        if target_node_ids is not None and unique_id not in target_node_ids:
            continue
        resource_type = node.get("resource_type")
        if resource_type not in {"model", "seed", "snapshot"}:
            continue
        materialized = str(node.get("config", {}).get("materialized") or "view").lower()
        if resource_type == "model" and materialized == "ephemeral":
            continue
        if resource_type in {"seed", "snapshot"}:
            expected_type = "table"
        elif materialized in {"table", "incremental", "materialized_view"}:
            expected_type = "table" if materialized != "materialized_view" else "view"
        elif materialized == "view":
            expected_type = "view"
        else:
            failures.append(f"Unsupported physical materialization '{materialized}' for {unique_id}")
            expected_type = "unsupported"

        columns = []
        for column_name, column in node.get("columns", {}).items():
            columns.append(
                {
                    "name": str(column.get("name") or column_name),
                    "data_type": str(column.get("data_type") or ""),
                }
            )
        expected.append(
            {
                "unique_id": unique_id,
                "resource_type": resource_type,
                "database": str(node.get("database") or ""),
                "schema": str(node.get("schema") or ""),
                "name": str(node.get("alias") or node.get("name") or ""),
                "materialized": materialized,
                "expected_type": expected_type,
                "columns": columns,
            }
        )
    if not expected and target_node_ids is None:
        failures.append("dbt manifest contains no physical models, seeds, or snapshots to validate")
    return expected, failures


def verify_dag(manifest_path: Path) -> dict[str, object]:
    """Parse dbt manifest DAG and extract model, seed, snapshot, source, and test metrics."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "failed", "failures": [f"Could not read manifest for DAG verification: {exc}"]}

    nodes = manifest.get("nodes", {})
    sources = manifest.get("sources", {})
    parent_map = manifest.get("parent_map", {})

    failures: list[str] = []
    model_counts: dict[str, int] = {}
    total_models = 0
    seeds = 0
    snapshots = 0
    tests = 0

    for unique_id, node in nodes.items():
        res_type = node.get("resource_type")
        if res_type == "model":
            total_models += 1
            mat = str(node.get("config", {}).get("materialized") or "view").lower()
            model_counts[mat] = model_counts.get(mat, 0) + 1
        elif res_type == "seed":
            seeds += 1
        elif res_type == "snapshot":
            snapshots += 1
        elif res_type == "test":
            tests += 1

    checked_deps = sum(len(parents) for parents in parent_map.values())

    status = "passed" if not failures else "failed"
    return {
        "status": status,
        "models_count": total_models,
        "models_by_materialization": model_counts,
        "seeds_count": seeds,
        "snapshots_count": snapshots,
        "tests_count": tests,
        "sources_count": len(sources),
        "dependencies_checked": checked_deps,
        "failures": failures,
    }


def validate_materialization_policy(
    manifest_path: Path,
    safe_materializations: tuple[str, ...],
) -> list[str]:
    """Reject custom materializations outside the configured rerun-safe set."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Could not validate materialization policy from dbt manifest: {exc}"]

    allowed = {value.casefold() for value in safe_materializations}
    failures = []
    for unique_id, node in manifest.get("nodes", {}).items():
        if node.get("resource_type") != "model":
            continue
        materialized = str(node.get("config", {}).get("materialized") or "view").casefold()
        if materialized not in allowed:
            model_name = str(node.get("alias") or node.get("name") or unique_id)
            failures.append(
                f"Model {model_name} uses materialization '{materialized}', which is not configured as rerun-safe"
            )
    return failures


def core_type_family(raw_type: str) -> str | None:
    """Map DuckDB/dbt type spellings to portable core type families."""
    value = re.sub(r"\s+", " ", raw_type.strip().upper())
    if not value:
        return None
    # 1. Complex types (arrays, lists, maps, structs, unions) must be checked first
    if value.endswith("[]") or value.startswith(("ARRAY", "LIST", "STRUCT(", "MAP(", "UNION(")):
        return "complex"
    # 2. Timestamps vs Dates (TIMESTAMP / DATETIME must come before DATE)
    if value.startswith(("TIMESTAMP", "DATETIME", "TIMESTAMPTZ")):
        return "timestamp"
    if value.startswith("DATE"):
        return "date"
    if value.startswith(("TIME", "TIMETZ")):
        return "time"
    if value.startswith("INTERVAL"):
        return "interval"
    if value.startswith((
        "TINYINT", "SMALLINT", "INTEGER", "INT", "BIGINT", "HUGEINT",
        "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "SHORT", "LONG"
    )):
        return "integer"
    if value.startswith(("FLOAT", "REAL", "DOUBLE")):
        return "floating"
    if value.startswith(("DECIMAL", "NUMERIC", "NUMBER")):
        return "decimal"
    if value.startswith(("CHAR", "VARCHAR", "STRING", "TEXT", "ENUM")):
        return "string"
    if value.startswith(("BOOL",)):
        return "boolean"
    if value.startswith(("BLOB", "BYTEA", "BINARY", "VARBINARY", "BIT")):
        return "binary"
    if value.startswith("UUID"):
        return "uuid"
    if value.startswith("JSON"):
        return "json"
    # User-defined enums or custom DuckDB types
    return "custom"


def validate_catalog(
    manifest_path: Path,
    catalog_path: Path,
    target_node_ids: set[str] | None = None,
) -> dict[str, object]:
    """Require expected DAG relations to exist in catalog with valid column types."""
    expected, failures = expected_relations(manifest_path, target_node_ids=target_node_ids)
    result: dict[str, object] = {
        "status": "failed",
        "expected_objects": expected,
        "actual_objects": [],
        "failures": failures,
        "additional_or_preexisting_objects": [],
    }
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"Could not read dbt catalog: {exc}")
        return result

    actual: list[dict[str, object]] = []
    for node in catalog.get("nodes", {}).values():
        metadata = node.get("metadata", {})
        columns = [
            {
                "name": str(column.get("name") or ""),
                "data_type": str(column.get("type") or ""),
            }
            for column in node.get("columns", {}).values()
        ]
        actual.append(
            {
                "unique_id": str(node.get("unique_id") or ""),
                "resource_type": str(node.get("resource_type") or ""),
                "database": str(metadata.get("database") or ""),
                "schema": str(metadata.get("schema") or ""),
                "name": str(metadata.get("name") or ""),
                "relation_type": str(metadata.get("type") or ""),
                "columns": columns,
            }
        )
    result["actual_objects"] = actual

    key = lambda item: tuple(str(item.get(part, "")).casefold() for part in ("database", "schema", "name"))
    expected_by_key = {key(item): item for item in expected}
    actual_by_key = {key(item): item for item in actual}

    for relation_key in sorted(expected_by_key.keys() - actual_by_key.keys()):
        item = expected_by_key[relation_key]
        failures.append(
            f"Missing expected {item['resource_type']} relation "
            f"{item['database']}.{item['schema']}.{item['name']}"
        )

    # Extra relations in catalog (pre-existing tables, sources) are recorded, not treated as fatal failures
    extra_objects = []
    for relation_key in sorted(actual_by_key.keys() - expected_by_key.keys()):
        item = actual_by_key[relation_key]
        extra_objects.append(
            f"{item['database']}.{item['schema']}.{item['name']} ({item.get('relation_type', 'TABLE')})"
        )
    result["additional_or_preexisting_objects"] = extra_objects

    for relation_key in expected_by_key.keys() & actual_by_key.keys():
        wanted = expected_by_key[relation_key]
        found = actual_by_key[relation_key]
        actual_type = str(found["relation_type"]).upper()
        actual_family = "view" if "VIEW" in actual_type else "table" if "TABLE" in actual_type or actual_type == "SEED" else "unsupported"
        if actual_family != wanted["expected_type"]:
            failures.append(
                f"Wrong object type for {wanted['database']}.{wanted['schema']}.{wanted['name']}: "
                f"expected {wanted['expected_type']}, got {found['relation_type']}"
            )

        found_columns = {str(column["name"]).casefold(): column for column in found["columns"]}
        if not found_columns:
            failures.append(f"Relation {wanted['schema']}.{wanted['name']} has no introspected columns")
        for column in found["columns"]:
            family = core_type_family(str(column["data_type"]))
            if family is None:
                failures.append(
                    f"Unsupported or missing core data type for {wanted['schema']}.{wanted['name']}.{column['name']}: "
                    f"{column['data_type'] or '<empty>'}"
                )
        for contract in wanted["columns"]:
            column_name = str(contract["name"])
            found_column = found_columns.get(column_name.casefold())
            if found_column is None:
                failures.append(
                    f"Missing declared column {wanted['schema']}.{wanted['name']}.{column_name}"
                )
                continue
            declared = str(contract["data_type"])
            if declared:
                expected_family = core_type_family(declared)
                actual_family = core_type_family(str(found_column["data_type"]))
                if expected_family is None:
                    failures.append(
                        f"Unsupported declared data type for {wanted['schema']}.{wanted['name']}.{column_name}: {declared}"
                    )
                elif expected_family != actual_family and "custom" not in (expected_family, actual_family):
                    failures.append(
                        f"Wrong data type for {wanted['schema']}.{wanted['name']}.{column_name}: "
                        f"expected {declared} ({expected_family}), got {found_column['data_type']} ({actual_family})"
                    )

    result["status"] = "passed" if not failures else "failed"
    return result


def verify_database_objects_direct(
    database_file: Path,
    manifest_path: Path,
    db_type: str = "duckdb",
    data_dir: Path | None = None,
    duckdb_extensions: Path | None = None,
    target_node_ids: set[str] | None = None,
) -> dict[str, object]:
    """Connect directly to DuckDB to verify physical objects and test view query execution."""
    expected, failures = expected_relations(manifest_path, target_node_ids=target_node_ids)
    result: dict[str, object] = {
        "status": "failed",
        "expected_objects": expected,
        "actual_objects": [],
        "failures": failures,
        "additional_or_preexisting_objects": [],
    }
    try:
        import duckdb
    except ImportError:
        result["failures"].append("duckdb python package is not installed; direct verification skipped")
        return result

    if not database_file.exists():
        result["failures"].append(f"Database file does not exist: {database_file}")
        return result

    try:
        conn = duckdb.connect(":memory:")
        if duckdb_extensions and duckdb_extensions.is_dir():
            conn.execute(f"SET extension_directory = '{duckdb_extensions}'")

        if db_type == "ducklake" and data_dir and data_dir.is_dir():
            conn.execute("INSTALL ducklake; LOAD ducklake;")
            conn.execute(
                f"ATTACH 'ducklake:{database_file}' AS ducklake (DATA_PATH '{data_dir}', OVERRIDE_DATA_PATH TRUE, READ_ONLY TRUE)"
            )
            cat_name = "ducklake"
        else:
            conn.execute(f"ATTACH '{database_file}' AS dbt_db (READ_ONLY)")
            cat_name = "dbt_db"

        tables_query = (
            f"SELECT table_catalog, table_schema, table_name, table_type "
            f"FROM information_schema.tables WHERE table_catalog = '{cat_name}'"
        )
        rows = conn.execute(tables_query).fetchall()

        # Query columns
        columns_query = (
            f"SELECT table_schema, table_name, column_name, data_type "
            f"FROM information_schema.columns WHERE table_catalog = '{cat_name}'"
        )
        cols_by_tbl: dict[tuple[str, str], list[dict[str, str]]] = {}
        try:
            for sch_col, tbl_col, cname, dtype in conn.execute(columns_query).fetchall():
                cols_by_tbl.setdefault((sch_col.casefold(), tbl_col.casefold()), []).append({
                    "name": str(cname),
                    "data_type": str(dtype),
                })
        except Exception:
            pass

        actual: list[dict[str, object]] = []
        for cat, sch, name, t_type in rows:
            if sch.lower() in {"information_schema", "pg_catalog"}:
                continue
            cols = cols_by_tbl.get((sch.casefold(), name.casefold()), [])
            actual.append({
                "database": cat,
                "schema": sch,
                "name": name,
                "relation_type": t_type,
                "columns": cols,
            })
            # If it's a view, verify that it can be queried without runtime errors
            if "VIEW" in t_type.upper():
                try:
                    conn.execute(f'SELECT * FROM "{cat}"."{sch}"."{name}" LIMIT 0')
                except Exception as view_err:
                    failures.append(f"View {sch}.{name} query execution failed: {view_err}")

        result["actual_objects"] = actual

        key = lambda item: tuple(str(item.get(part, "")).casefold() for part in ("schema", "name"))
        expected_by_key = {key(item): item for item in expected}
        actual_by_key = {key(item): item for item in actual}

        for rel_key in sorted(expected_by_key.keys() - actual_by_key.keys()):
            item = expected_by_key[rel_key]
            failures.append(
                f"Missing expected {item['resource_type']} relation {item['schema']}.{item['name']}"
            )

        for rel_key in expected_by_key.keys() & actual_by_key.keys():
            wanted = expected_by_key[rel_key]
            found = actual_by_key[rel_key]
            actual_type = str(found["relation_type"]).upper()
            actual_family = "view" if "VIEW" in actual_type else "table" if "TABLE" in actual_type or actual_type == "SEED" else "unsupported"
            if actual_family != wanted["expected_type"]:
                failures.append(
                    f"Wrong object type for {wanted['schema']}.{wanted['name']}: "
                    f"expected {wanted['expected_type']}, got {found['relation_type']}"
                )

            found_columns = {str(c["name"]).casefold(): c for c in found.get("columns", [])}
            for contract in wanted.get("columns", []):
                col_name = str(contract["name"])
                fc = found_columns.get(col_name.casefold())
                if fc is None:
                    failures.append(f"Missing declared column {wanted['schema']}.{wanted['name']}.{col_name}")
                elif contract.get("data_type"):
                    exp_fam = core_type_family(str(contract["data_type"]))
                    act_fam = core_type_family(str(fc["data_type"]))
                    if exp_fam and act_fam and exp_fam != act_fam and "custom" not in (exp_fam, act_fam):
                        failures.append(
                            f"Wrong data type for {wanted['schema']}.{wanted['name']}.{col_name}: "
                            f"expected {contract['data_type']} ({exp_fam}), got {fc['data_type']} ({act_fam})"
                        )

        extra_objects = []
        for rel_key in sorted(actual_by_key.keys() - expected_by_key.keys()):
            item = actual_by_key[rel_key]
            extra_objects.append(
                f"{item['schema']}.{item['name']} ({item.get('relation_type', 'TABLE')})"
            )
        result["additional_or_preexisting_objects"] = extra_objects

        conn.close()
        result["status"] = "passed" if not failures else "failed"
    except Exception as exc:
        result["failures"].append(f"Direct DuckDB inspection error: {exc}")
        result["status"] = "failed"

    return result


def enrich_objects_with_samples(
    actual_objects: list[dict[str, Any]],
    database_file: Path,
    db_type: str = "duckdb",
    data_dir: Path | None = None,
    duckdb_extensions: Path | None = None,
    sample_limit: int = 15,
) -> None:
    """Connect to database and attach row count and sample rows to each actual object."""
    try:
        import duckdb
    except ImportError:
        return

    if not database_file.exists():
        return

    try:
        conn = duckdb.connect(":memory:")
        if duckdb_extensions and duckdb_extensions.is_dir():
            conn.execute(f"SET extension_directory = '{duckdb_extensions}'")

        if db_type == "ducklake" and data_dir and data_dir.is_dir():
            conn.execute("INSTALL ducklake; LOAD ducklake;")
            conn.execute(
                f"ATTACH 'ducklake:{database_file}' AS ducklake (DATA_PATH '{data_dir}', OVERRIDE_DATA_PATH TRUE, READ_ONLY TRUE)"
            )
            cat_name = "ducklake"
        else:
            conn.execute(f"ATTACH '{database_file}' AS dbt_db (READ_ONLY)")
            cat_name = "dbt_db"

        for obj in actual_objects:
            sch = str(obj.get("schema") or "main")
            name = str(obj.get("name") or "")
            if not name:
                continue

            # 1. Total row count
            try:
                cnt_row = conn.execute(f'SELECT COUNT(*) FROM "{cat_name}"."{sch}"."{name}"').fetchone()
                obj["row_count"] = cnt_row[0] if cnt_row else 0
            except Exception:
                obj["row_count"] = None

            # 2. Sample rows
            try:
                cur = conn.execute(f'SELECT * FROM "{cat_name}"."{sch}"."{name}" LIMIT {sample_limit}')
                columns = [desc[0] for desc in cur.description] if cur.description else []
                obj["sample_columns"] = columns
                raw_rows = cur.fetchall()
                sample_rows = []
                for r in raw_rows:
                    row_dict = {}
                    for col_name, val in zip(columns, r):
                        if val is None:
                            row_dict[col_name] = None
                        elif isinstance(val, (int, float, bool, str)):
                            row_dict[col_name] = val
                        else:
                            row_dict[col_name] = str(val)
                    sample_rows.append(row_dict)
                obj["sample_rows"] = sample_rows
            except Exception:
                obj["sample_columns"] = [c.get("name") for c in obj.get("columns", [])] if isinstance(obj.get("columns"), list) else []
                obj["sample_rows"] = []

        conn.close()
    except Exception:
        pass


def parse_run_results(
    target_dir: Path,
    manifest_path: Path | None = None,
) -> tuple[list[dict[str, object]], list[str]]:
    result_path = target_dir / "run_results.json"
    if not result_path.is_file():
        return [], []
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"Could not read dbt run_results.json: {exc}"]

    manifest_nodes: dict[str, dict[str, object]] = {}
    if manifest_path and manifest_path.is_file():
        try:
            manifest_nodes = json.loads(manifest_path.read_text(encoding="utf-8")).get("nodes", {})
        except (OSError, json.JSONDecodeError):
            manifest_nodes = {}

    results: list[dict[str, object]] = []
    failures: list[str] = []
    for item in payload.get("results", []):
        node = item.get("unique_id", "unknown node")
        status = str(item.get("status", "unknown"))
        message = str(item.get("message") or "")
        resource_type = str(item.get("unique_id", "")).split(".", 1)[0]
        manifest_node = manifest_nodes.get(node, {})
        config = manifest_node.get("config") or {}
        if resource_type == "model":
            object_type = str(config.get("materialized") or "view")
        elif resource_type in {"seed", "snapshot"}:
            object_type = "table"
        else:
            object_type = resource_type
        model_name = str(manifest_node.get("alias") or manifest_node.get("name") or node)
        database = str(manifest_node.get("database") or "")
        schema = str(manifest_node.get("schema") or "")
        relation_name = str(item.get("relation_name") or ".".join(part for part in (schema, model_name) if part))
        try:
            duration = float(item.get("execution_time") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0

        is_warning = status.casefold() in {"warn", "warning"}
        failed = status.casefold() not in {"pass", "success", "warn", "warning"}

        result = {
            "node": node,
            "model": model_name,
            "resource_type": resource_type,
            "object_type": object_type,
            "database": database,
            "schema": schema,
            "relation_name": relation_name,
            "status": status,
            "execution_status": status,
            "duration_seconds": duration,
            "message": message,
            "error_message": message if failed else "",
            "is_warning": is_warning,
        }
        results.append(result)
        if failed:
            failures.append(
                f"{model_name} ({object_type}) {status} after {duration:.3f}s"
                + (f": {message}" if message else f" ({node})")
            )
    return results, failures

