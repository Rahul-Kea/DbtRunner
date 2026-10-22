from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml


def clean_path(raw: str) -> Path:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return Path(value).expanduser().resolve()


def validate_project_directory(project_dir: Path) -> str | None:
    if not project_dir.is_dir():
        return f"Project directory does not exist: {project_dir}"
    if not (project_dir / "dbt_project.yml").is_file():
        return f"No dbt_project.yml found in {project_dir}"
    return None


def detect_database_type(database_path: Path, data_dir: Path | None = None) -> str:
    if database_path.suffix.lower() == ".ducklake" or (data_dir is not None and data_dir.is_dir()):
        return "ducklake"
    return "duckdb"


def validate_database_inputs(database_path: Path, data_dir: Path | None = None) -> tuple[str, str | None]:
    if not database_path.is_file():
        return "unknown", f"Database / metadata file does not exist: {database_path}"
    db_type = detect_database_type(database_path, data_dir)
    if db_type == "ducklake":
        if data_dir is None or not data_dir.is_dir():
            return "ducklake", f"DuckLake requires a valid data directory containing Parquet files: {data_dir}"
    return db_type, None


def read_profile_name(project_dir: Path) -> str:
    project_file = project_dir / "dbt_project.yml"
    if not project_file.is_file():
        raise ValueError(f"No dbt_project.yml found in {project_dir}")
    try:
        project_config = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not parse {project_file} as YAML: {exc}") from exc

    if not isinstance(project_config, dict):
        raise ValueError(f"Expected {project_file} to contain a YAML mapping at its root")
    profile_name = project_config.get("profile")
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise ValueError(
            f"Expected {project_file} to define a non-empty top-level 'profile' string"
        )
    return profile_name.strip()


def yaml_quote(value: str) -> str:
    return json.dumps(value)


def write_profile(
    path: Path,
    profile_name: str,
    data_dir: Path | None,
    metadata: Path,
    duckdb_extensions: Path,
    db_type: str,
    default_schema: str | None = None,
    target_database: str | None = None,
    attachments: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    catalog_mappings: dict[str, str] | None = None,
) -> None:
    if not default_schema:
        raise ValueError("A target schema must be resolved from the project profile or explicit run configuration")
    attached_aliases: set[str] = set()
    extra_attach_entries: list[list[str]] = []

    # 1. Process explicit user-supplied attachments
    if attachments:
        for att in attachments:
            alias = str(att.get("alias") or "").strip()
            att_path = str(att.get("path") or ":memory:").strip()
            if alias and alias not in attached_aliases:
                attached_aliases.add(alias)
                lines = [
                    f"        - path: {yaml_quote(att_path)}",
                    f"          alias: {alias}",
                ]
                if att.get("read_only"):
                    lines.append("          read_only: true")
                if att.get("options") and isinstance(att["options"], dict):
                    lines.append("          options:")
                    for opt_k, opt_v in att["options"].items():
                        lines.append(f"            {opt_k}: {yaml_quote(str(opt_v))}")
                extra_attach_entries.append(lines)

    # 2. Process catalog mappings: provision in-memory databases for unattached mapped catalogs
    if catalog_mappings:
        for src_cat in catalog_mappings.keys():
            clean_src = str(src_cat).strip()
            if clean_src and clean_src not in attached_aliases:
                attached_aliases.add(clean_src)
                extra_attach_entries.append([
                    f"        - path: \":memory:\"",
                    f"          alias: {clean_src}",
                ])

    if db_type == "ducklake" and data_dir is not None:
        primary_alias = target_database or metadata.stem
        active_db = target_database or metadata.stem
        attached_aliases.add(primary_alias)

        attach_block = [
            "      attach:",
            f"        - path: {yaml_quote('ducklake:' + str(metadata))}",
            f"          alias: {primary_alias}",
            "          options:",
            f"            data_path: {yaml_quote(str(data_dir))}",
            "            override_data_path: true",
        ]
        for lines in extra_attach_entries:
            # Avoid re-attaching primary alias
            if any(f"alias: {primary_alias}" in l for l in lines):
                continue
            attach_block.extend(lines)

        content = [
            f"{profile_name}:",
            "  target: runner",
            "  outputs:",
            "    runner:",
            "      type: duckdb",
            '      path: ":memory:"',
            f"      database: {active_db}",
            f"      schema: {default_schema}",
            "      config_options:",
            f"        extension_directory: {yaml_quote(str(duckdb_extensions))}",
            "      extensions:",
            "        - ducklake",
            *attach_block,
            "",
        ]
    elif extra_attach_entries or target_database:
        primary_alias = target_database or metadata.stem
        active_db = target_database or primary_alias
        attached_aliases.add(primary_alias)

        attach_block = [
            "      attach:",
            f"        - path: {yaml_quote(str(metadata))}",
            f"          alias: {primary_alias}",
        ]
        for lines in extra_attach_entries:
            if any(f"alias: {primary_alias}" in l for l in lines):
                continue
            attach_block.extend(lines)

        content = [
            f"{profile_name}:",
            "  target: runner",
            "  outputs:",
            "    runner:",
            "      type: duckdb",
            '      path: ":memory:"',
            f"      database: {active_db}",
            f"      schema: {default_schema}",
            "      config_options:",
            f"        extension_directory: {yaml_quote(str(duckdb_extensions))}",
            *attach_block,
            "",
        ]
    else:
        # Default single-file DuckDB output (full backward compatibility)
        content = [
            f"{profile_name}:",
            "  target: runner",
            "  outputs:",
            "    runner:",
            "      type: duckdb",
            f"      path: {yaml_quote(str(metadata))}",
            f"      schema: {default_schema}",
            "      config_options:",
            f"        extension_directory: {yaml_quote(str(duckdb_extensions))}",
            "",
        ]
    path.write_text("\n".join(content), encoding="utf-8")


def write_catalog_clone_script(path: Path) -> None:
    """Write a DuckDB-backed logical catalog-copy script for the run sandbox."""
    path.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "import duckdb",
                "",
                "def sql_string(value):",
                "    return \"'\" + str(value).replace(\"'\", \"''\") + \"'\"",
                "",
                "source = Path(sys.argv[1]).resolve()",
                "destination = Path(sys.argv[2]).resolve()",
                "if not source.is_file():",
                "    raise FileNotFoundError(f'DuckLake metadata catalog not found: {source}')",
                "if destination.exists():",
                "    raise FileExistsError(f'Sandbox catalog already exists: {destination}')",
                "connection = duckdb.connect(':memory:')",
                "try:",
                "    connection.execute(f\"ATTACH {sql_string(source)} AS source_catalog (READ_ONLY)\")",
                "    connection.execute(f\"ATTACH {sql_string(destination)} AS sandbox_catalog\")",
                "    connection.execute('COPY FROM DATABASE source_catalog TO sandbox_catalog')",
                "finally:",
                "    connection.close()",
                "print(f'Cloned DuckLake metadata catalog to {destination}')",
                "",
            ]
        ),
        encoding="utf-8",
    )


def clone_database_file(source: Path, destination: Path) -> None:
    """Safely clone a DuckDB file and any sidecars into the sandbox."""
    shutil.copy2(source, destination)
    for suffix in (".wal", "-wal", "-shm"):
        sidecar = Path(str(source) + suffix)
        if sidecar.is_file():
            shutil.copy2(sidecar, Path(str(destination) + suffix))


def copy_project_to_sandbox(
    project: Path,
    destination: Path,
    source_data_dir: Path | None,
    source_metadata: Path,
) -> None:
    for candidate in project.rglob("*"):
        if candidate.is_symlink():
            try:
                candidate.resolve(strict=True).relative_to(project.resolve())
            except (OSError, ValueError) as exc:
                raise ValueError(f"Project symlink escapes the project workspace: {candidate.relative_to(project)}") from exc
    ignored_root_items = {".git", ".venv", "venv", "target", "dbt_packages", "logs", "run_logs"}
    source_data_dir = source_data_dir.resolve() if source_data_dir else None
    source_metadata = source_metadata.resolve()
    source_sidecars = {
        Path(str(source_metadata) + suffix).resolve()
        for suffix in (".wal", ".tmp", "-wal", "-shm")
    }

    def ignore(directory: str, names: list[str]) -> set[str]:
        parent = Path(directory)
        ignored: set[str] = set()
        is_project_root = parent.resolve() == project.resolve()
        for name in names:
            candidate = (parent / name).resolve()
            if name == "__pycache__" or (is_project_root and name in ignored_root_items):
                ignored.add(name)
            elif candidate == source_data_dir or candidate == source_metadata or candidate in source_sidecars:
                ignored.add(name)
        return ignored

    shutil.copytree(project, destination, symlinks=True, ignore=ignore)


def copy_data_to_sandbox(
    source_data_dir: Path,
    destination_data_dir: Path,
) -> None:
    if not source_data_dir.is_dir():
        raise ValueError(f"DuckLake data directory does not exist: {source_data_dir}")
    shutil.copytree(source_data_dir, destination_data_dir, symlinks=True)
