from __future__ import annotations

import json
from pathlib import Path

from dbt_runner.config import RunnerConfig, load_config


def test_default_config(tmp_path: Path) -> None:
    config_file = tmp_path / "runner_config.json"
    config_file.write_text(json.dumps({
        "dbt_package": "dbt-duckdb",
        "run_logs_dir": str(tmp_path / "logs"),
        "safe_materializations": ["table", "view"],
    }), encoding="utf-8")

    cfg = load_config(path=config_file)
    assert cfg.dbt_package == "dbt-duckdb"
    assert cfg.target_database is None
    assert cfg.target_schema is None
    assert cfg.attachments == ()
    assert cfg.catalog_mappings_dict == {}


def test_project_level_config_json_override(tmp_path: Path) -> None:
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    (project_dir / "runner_config.json").write_text(json.dumps({
        "target_database": "analytics",
        "target_schema": "dbt_prod",
        "catalog_mappings": {
            "raw": "ducklake",
            "analytics": "ducklake",
        },
        "attachments": [
            {"alias": "custom_raw", "path": ":memory:"}
        ]
    }), encoding="utf-8")

    cfg = load_config(project_dir=project_dir)
    assert cfg.target_database == "analytics"
    assert cfg.target_schema == "dbt_prod"
    assert cfg.catalog_mappings_dict == {"raw": "ducklake", "analytics": "ducklake"}
    assert len(cfg.attachments) == 1
    assert cfg.attachments[0]["alias"] == "custom_raw"


def test_project_level_dbt_project_yml_override(tmp_path: Path) -> None:
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text(
        "name: test_proj\n"
        "version: 1.0.0\n"
        "vars:\n"
        "  runner:\n"
        "    target_database: my_warehouse\n"
        "    target_schema: reporting\n"
        "    catalog_mappings:\n"
        "      raw: my_warehouse\n",
        encoding="utf-8"
    )

    cfg = load_config(project_dir=project_dir)
    assert cfg.target_database == "my_warehouse"
    assert cfg.target_schema == "reporting"
    assert cfg.catalog_mappings_dict == {"raw": "my_warehouse"}
