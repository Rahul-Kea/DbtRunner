from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb


def sanitize_table_name(name: str) -> str:
    """Sanitize filename into a clean SQL identifier."""
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_").lower()
    if clean and clean[0].isdigit():
        clean = f"t_{clean}"
    return clean or "raw_table"


def build_ducklake_from_raw_data(
    raw_data_dir: Path,
    lake_metadata_path: Path,
    lake_data_dir: Path,
    default_schema: str = "main",
) -> list[dict[str, Any]]:
    """Automatically ingest CSV, Parquet, and JSON files from raw_data_dir into a fresh DuckLake catalog."""
    lake_data_dir.mkdir(parents=True, exist_ok=True)
    if lake_metadata_path.exists():
        lake_metadata_path.unlink()

    # Discover candidate raw data files
    supported_extensions = {".csv", ".tsv", ".parquet", ".json", ".ndjson"}
    raw_files: list[Path] = []

    if raw_data_dir.is_file():
        if raw_data_dir.suffix.lower() in supported_extensions:
            raw_files.append(raw_data_dir)
    elif raw_data_dir.is_dir():
        for p in raw_data_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in supported_extensions:
                # Skip hidden files or macOS metadata
                if any(part.startswith((".", "__MACOSX")) for part in p.parts):
                    continue
                raw_files.append(p)

    if not raw_files:
        raise ValueError(
            f"No supported data files (.csv, .parquet, .json) found in uploaded data: {raw_data_dir}"
        )

    con = duckdb.connect(":memory:")
    try:
        con.execute("LOAD ducklake;")
        con.execute(
            f"ATTACH 'ducklake:{lake_metadata_path.resolve()}' AS lake (DATA_PATH '{lake_data_dir.resolve()}');"
        )

        ingested_tables: list[dict[str, Any]] = []

        for file_path in raw_files:
            table_name = sanitize_table_name(file_path.stem)
            ext = file_path.suffix.lower()

            # Escape single quotes in file path for SQL
            escaped_path = str(file_path.resolve()).replace("'", "''")

            if ext in {".csv", ".tsv"}:
                query = f"CREATE TABLE lake.{default_schema}.{table_name} AS SELECT * FROM read_csv_auto('{escaped_path}', header=True);"
            elif ext == ".parquet":
                query = f"CREATE TABLE lake.{default_schema}.{table_name} AS SELECT * FROM read_parquet('{escaped_path}');"
            elif ext in {".json", ".ndjson"}:
                query = f"CREATE TABLE lake.{default_schema}.{table_name} AS SELECT * FROM read_json_auto('{escaped_path}');"
            else:
                continue

            con.execute(query)

            # Query table row count and columns
            count_res = con.execute(f"SELECT count(*) FROM lake.{default_schema}.{table_name};").fetchone()
            row_count = count_res[0] if count_res else 0

            cols_res = con.execute(
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_schema = '{default_schema}' AND table_name = '{table_name}';"
            ).fetchall()
            columns = [{"name": c[0], "type": c[1]} for c in cols_res]

            ingested_tables.append({
                "table_name": table_name,
                "source_file": file_path.name,
                "row_count": row_count,
                "columns": columns,
            })

        # Checkpoint to commit transaction and write Parquet files to disk
        con.execute("CHECKPOINT lake;")

        return ingested_tables
    finally:
        con.close()
