import json
import shutil
import subprocess
from pathlib import Path

import duckdb


simulation = Path("simulation")
if simulation.exists():
    shutil.rmtree(simulation)

(simulation / "lake_data").mkdir(parents=True)

con = duckdb.connect(":memory:")
con.execute("LOAD ducklake;")
con.execute("""
    ATTACH 'ducklake:simulation/simulation.ducklake'
    AS lake (DATA_PATH 'simulation/lake_data');
""")
con.execute("""
    CREATE TABLE lake.main.store_orders AS
    SELECT *
    FROM read_csv_auto('seeds/store_orders.csv', header=True)
""")

print("Before:", con.execute("""
    SELECT table_schema, table_name, table_type
    FROM information_schema.tables
    WHERE table_schema = 'main'
    ORDER BY table_name
""").fetchall())
con.close()

subprocess.run([
    "dbt", "run",
    "--project-dir", ".",
    "--profiles-dir", ".",
    "--no-use-colors",
], check=True)

subprocess.run([
    "dbt", "docs", "generate",
    "--project-dir", ".",
    "--profiles-dir", ".",
    "--no-use-colors",
], check=True)

catalog_path = Path("target/catalog.json")
catalog = json.loads(catalog_path.read_text())
print("Catalog generated at:", catalog.get("metadata", {}).get("generated_at"))
print("Catalog metadata:")
catalog_relations = [
    *catalog.get("nodes", {}).values(),
    *catalog.get("sources", {}).values(),
]
for relation in sorted(
    catalog_relations,
    key=lambda item: item.get("metadata", {}).get("name", ""),
):
    metadata = relation.get("metadata", {})
    relation_name = ".".join(
        part for part in (
            metadata.get("database"),
            metadata.get("schema"),
            metadata.get("name"),
        ) if part
    )
    print(f"  {relation_name} ({metadata.get('type', 'unknown')})")
    columns = sorted(
        relation.get("columns", {}).values(),
        key=lambda column: column.get("index", 0),
    )
    for column in columns:
        print(f"    {column.get('name')}: {column.get('type')}")

con = duckdb.connect(":memory:")
con.execute("LOAD ducklake;")
con.execute("""
    ATTACH 'ducklake:simulation/simulation.ducklake'
    AS lake (DATA_PATH 'simulation/lake_data');
""")

print("After:", con.execute("""
    SELECT table_schema, table_name, table_type
    FROM information_schema.tables
    WHERE table_schema = 'main'
    ORDER BY table_name
""").fetchall())
con.close()
