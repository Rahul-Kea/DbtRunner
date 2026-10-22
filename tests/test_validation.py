from __future__ import annotations

import json
from pathlib import Path
import duckdb

from dbt_runner.validation import validate_project_prerequisites


def test_catalog_mismatch_detection(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "nodes": {
            "snapshot.test_proj.scd_mock_orders": {
                "resource_type": "snapshot",
                "name": "scd_mock_orders",
                "database": "analytics",
                "schema": "main",
                "raw_sql": "select * from analytics.main.mock_orders"
            }
        },
        "sources": {
            "source.test_proj.jaffle_shop.orders": {
                "name": "orders",
                "database": "raw",
                "schema": "jaffle_shop",
            }
        },
        "parent_map": {
            "snapshot.test_proj.scd_mock_orders": ["source.test_proj.jaffle_shop.orders"]
        }
    }), encoding="utf-8")

    db_file = tmp_path / "duck.db"
    res = validate_project_prerequisites(
        manifest_path=manifest_path,
        database_file=db_file,
        db_type="duckdb",
        primary_database="ducklake",
        has_seeds=False,
    )
    assert res["status"] == "failed"
    failures = " ".join(res["failures"])
    assert "MissingSourceData" in failures


def test_missing_source_table_detection(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "nodes": {
            "model.test_proj.stg_orders": {
                "resource_type": "model",
                "name": "stg_orders",
                "database": "ducklake",
                "schema": "main",
            }
        },
        "sources": {
            "source.test_proj.jaffle_shop.orders": {
                "name": "orders",
                "database": "ducklake",
                "schema": "main",
            }
        },
        "parent_map": {
            "model.test_proj.stg_orders": ["source.test_proj.jaffle_shop.orders"]
        }
    }), encoding="utf-8")

    db_file = tmp_path / "duck.db"
    conn = duckdb.connect(str(db_file))
    conn.execute("CREATE TABLE other_table (id INT)")
    conn.close()

    res = validate_project_prerequisites(
        manifest_path=manifest_path,
        database_file=db_file,
        db_type="duckdb",
        primary_database="ducklake",
        has_seeds=False,
    )
    assert res["status"] == "failed"
    failures = " ".join(res["failures"])
    assert "MissingSourceData: required relation ducklake.main.orders" in failures


def test_preexisting_source_table_passes_without_seeds(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "nodes": {
            "model.test_proj.stg_orders": {
                "resource_type": "model",
                "name": "stg_orders",
                "database": "ducklake",
                "schema": "main",
            }
        },
        "sources": {
            "source.test_proj.jaffle_shop.orders": {
                "name": "orders",
                "database": "ducklake",
                "schema": "main",
            }
        },
        "parent_map": {
            "model.test_proj.stg_orders": ["source.test_proj.jaffle_shop.orders"]
        }
    }), encoding="utf-8")

    db_file = tmp_path / "duck.db"
    conn = duckdb.connect(str(db_file))
    conn.execute("CREATE TABLE orders (id INT, status VARCHAR)")
    conn.close()

    res = validate_project_prerequisites(
        manifest_path=manifest_path,
        database_file=db_file,
        db_type="duckdb",
        primary_database="ducklake",
        has_seeds=False,
    )
    assert res["status"] == "passed"
    assert res["failures"] == []


def test_snapshot_dependency_detection(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "nodes": {
            "snapshot.test_proj.snap_after_model": {
                "resource_type": "snapshot",
                "name": "snap_after_model",
                "database": "ducklake",
                "schema": "main",
            },
            "model.test_proj.stg_orders": {
                "resource_type": "model",
                "name": "stg_orders",
                "database": "ducklake",
                "schema": "main",
            }
        },
        "sources": {},
        "parent_map": {
            "snapshot.test_proj.snap_after_model": ["model.test_proj.stg_orders"]
        }
    }), encoding="utf-8")

    db_file = tmp_path / "duck.db"
    res = validate_project_prerequisites(
        manifest_path=manifest_path,
        database_file=db_file,
        db_type="duckdb",
        primary_database="ducklake",
        has_seeds=True,
    )
    assert res["snapshots_depend_on_models"] is True
