from __future__ import annotations

from pathlib import Path
import yaml

from dbt_runner.project import write_profile


def test_write_profile_ducklake_default_backward_compatible(tmp_path: Path) -> None:
    profile_path = tmp_path / "profiles.yml"
    data_dir = tmp_path / "lake_data"
    data_dir.mkdir()
    metadata = tmp_path / "sim.ducklake"
    metadata.touch()
    ext_dir = tmp_path / "extensions"

    write_profile(
        profile_path,
        "default_profile",
        data_dir,
        metadata,
        ext_dir,
        db_type="ducklake",
        default_schema="resolved_schema",
    )

    content = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    target = content["default_profile"]["outputs"]["runner"]
    assert target["type"] == "duckdb"
    assert target["path"] == ":memory:"
    assert target["database"] == "sim"
    assert target["schema"] == "resolved_schema"
    assert target["attach"][0]["alias"] == "sim"
    assert target["attach"][0]["path"] == f"ducklake:{metadata}"


def test_write_profile_duckdb_default_backward_compatible(tmp_path: Path) -> None:
    profile_path = tmp_path / "profiles.yml"
    metadata = tmp_path / "db.duckdb"
    metadata.touch()
    ext_dir = tmp_path / "extensions"

    write_profile(
        profile_path,
        "default_profile",
        None,
        metadata,
        ext_dir,
        db_type="duckdb",
        default_schema="resolved_schema",
    )

    content = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    target = content["default_profile"]["outputs"]["runner"]
    assert target["type"] == "duckdb"
    assert target["path"] == str(metadata)
    assert target["schema"] == "resolved_schema"
    assert "attach" not in target


def test_write_profile_custom_database_and_attachments(tmp_path: Path) -> None:
    profile_path = tmp_path / "profiles.yml"
    data_dir = tmp_path / "lake_data"
    data_dir.mkdir()
    metadata = tmp_path / "sim.ducklake"
    metadata.touch()
    ext_dir = tmp_path / "extensions"

    write_profile(
        profile_path,
        "custom_profile",
        data_dir,
        metadata,
        ext_dir,
        db_type="ducklake",
        default_schema="analytics_schema",
        target_database="analytics",
        attachments=[{"alias": "raw", "path": ":memory:"}],
        catalog_mappings={"staging_db": "analytics"},
    )

    content = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    target = content["custom_profile"]["outputs"]["runner"]
    assert target["database"] == "analytics"
    assert target["schema"] == "analytics_schema"
    aliases = [a["alias"] for a in target["attach"]]
    assert "analytics" in aliases
    assert "raw" in aliases
    assert "staging_db" in aliases
