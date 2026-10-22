from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "runner_config.json"


@dataclass(frozen=True)
class RunnerConfig:
    dbt_package: str | None
    run_logs_dir: Path
    safe_materializations: tuple[str, ...]
    config_path: Path
    verify_rerun: bool = True
    reuse_environment: bool = True
    timeout_seconds: int = 600
    compile_only: bool = False
    project_dir: Path | None = None
    database_path: Path | None = None
    data_dir: Path | None = None
    execution_mode: str = "run"
    full_refresh: bool = False
    select: str | None = None
    exclude: str | None = None
    vars: dict[str, object] = field(default_factory=dict)
    target_database: str | None = None
    target_schema: str | None = None
    adapter_type: str | None = None
    run_tests: bool = True
    file_mappings: tuple[tuple[str, dict[str, str]], ...] = ()
    approved_sql_scripts: tuple[str, ...] = ()
    sql_target_compatibility: str | None = None
    attachments: tuple[dict[str, object], ...] = ()
    catalog_mappings: tuple[tuple[str, str], ...] = ()
    schema_mappings: tuple[tuple[str, str], ...] = ()

    @property
    def catalog_mappings_dict(self) -> dict[str, str]:
        return dict(self.catalog_mappings)

    @property
    def schema_mappings_dict(self) -> dict[str, str]:
        return dict(self.schema_mappings)


def _read_project_level_config(project_dir: Path | None) -> dict[str, object]:
    """Read project-level runner settings from dbt_project.yml or a runner_config.json file."""
    if not project_dir or not project_dir.is_dir():
        return {}

    # 1. Project-level json configs
    for candidate in ("runner_config.json", "dbt_runner.json"):
        cfg_file = project_dir / candidate
        if cfg_file.is_file():
            try:
                data = json.loads(cfg_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                pass

    # 2. Check dbt_project.yml vars or meta
    dbt_proj_file = project_dir / "dbt_project.yml"
    if dbt_proj_file.is_file():
        try:
            import yaml
            data = yaml.safe_load(dbt_proj_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                vars_dict = data.get("vars", {})
                if isinstance(vars_dict, dict):
                    runner_vars = vars_dict.get("runner") or vars_dict.get("dbt_runner")
                    if isinstance(runner_vars, dict):
                        return runner_vars
                meta_dict = data.get("meta", {})
                if isinstance(meta_dict, dict):
                    runner_meta = meta_dict.get("runner") or meta_dict.get("dbt_runner")
                    if isinstance(runner_meta, dict):
                        return runner_meta
        except Exception:
            pass

    return {}


def load_config(path: Path | None = None, project_dir: Path | None = None) -> RunnerConfig:
    config_path = (path or CONFIG_PATH).resolve()
    try:
        values = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        values = {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid runner configuration {config_path}: {exc}") from exc

    # Merge project-level config if project_dir is known or in values
    proj_dir_candidate = project_dir
    if not proj_dir_candidate:
        p_val = values.get("project_dir")
        if p_val:
            proj_dir_candidate = Path(p_val).expanduser().resolve()

    project_level = _read_project_level_config(proj_dir_candidate)
    # Project-level config overrides global defaults for warehouse settings
    merged_values = dict(values)
    merged_values.update(project_level)

    package = merged_values.get("dbt_package")
    logs_value = merged_values.get("run_logs_dir", "run_logs")
    materializations = merged_values.get(
        "safe_materializations",
        ["table", "view", "incremental", "ephemeral", "materialized_view"],
    )
    verify_rerun = bool(merged_values.get("verify_rerun", True))
    reuse_env = bool(merged_values.get("reuse_environment", True))
    timeout_seconds = int(merged_values.get("timeout_seconds", 600))
    compile_only = bool(merged_values.get("compile_only", False))
    execution_mode = str(merged_values.get("execution_mode", "run")).strip().lower()
    if compile_only:
        execution_mode = "compile"
    elif execution_mode not in {"run", "compile"}:
        execution_mode = "run"
    full_refresh = bool(merged_values.get("full_refresh", False))
    select_val = merged_values.get("select")
    select = select_val.strip() if isinstance(select_val, str) and select_val.strip() else None
    exclude_val = merged_values.get("exclude")
    exclude = exclude_val.strip() if isinstance(exclude_val, str) and exclude_val.strip() else None
    vars_val = merged_values.get("vars")
    vars_config = dict(vars_val) if isinstance(vars_val, dict) else {}

    project_dir_val = merged_values.get("project_dir")
    resolved_proj_dir = Path(project_dir_val).expanduser().resolve() if project_dir_val else proj_dir_candidate

    db_path_val = merged_values.get("database_path") or merged_values.get("ducklake_metadata_location")
    database_path = Path(db_path_val).expanduser().resolve() if db_path_val else None

    data_dir_val = merged_values.get("data_dir") or merged_values.get("data_location")
    data_dir = Path(data_dir_val).expanduser().resolve() if data_dir_val else None

    # Flexible database, schema, attachment, and catalog mapping configs
    target_database = merged_values.get("target_database") or merged_values.get("database")
    if target_database is not None:
        target_database = str(target_database).strip()

    target_schema_value = merged_values.get("target_schema") or merged_values.get("schema")
    target_schema = str(target_schema_value).strip() if target_schema_value else None
    adapter_type_val = merged_values.get("adapter_type")
    adapter_type = str(adapter_type_val).strip().lower() if adapter_type_val else None
    run_tests = bool(merged_values.get("run_tests", True))

    raw_attachments = merged_values.get("attachments") or []
    parsed_attachments: list[dict[str, object]] = []
    if isinstance(raw_attachments, list):
        for item in raw_attachments:
            if isinstance(item, dict):
                parsed_attachments.append(dict(item))

    raw_cat_map = merged_values.get("catalog_mappings") or merged_values.get("database_mappings") or {}
    parsed_cat_map: list[tuple[str, str]] = []
    if isinstance(raw_cat_map, dict):
        for k, v in raw_cat_map.items():
            parsed_cat_map.append((str(k).strip(), str(v).strip()))

    raw_sch_map = merged_values.get("schema_mappings") or {}
    parsed_sch_map: list[tuple[str, str]] = []
    if isinstance(raw_sch_map, dict):
        for k, v in raw_sch_map.items():
            parsed_sch_map.append((str(k).strip(), str(v).strip()))

    raw_file_map = merged_values.get("file_mappings") or {}
    parsed_file_map: list[tuple[str, dict[str, str]]] = []
    if isinstance(raw_file_map, dict):
        for path, mapping in raw_file_map.items():
            if isinstance(mapping, dict):
                parsed_file_map.append((str(path), {str(k): str(v) for k, v in mapping.items()}))
    raw_approved_sql = merged_values.get("approved_sql_scripts") or []
    approved_sql_scripts = tuple(str(value) for value in raw_approved_sql if isinstance(value, str)) if isinstance(raw_approved_sql, list) else ()
    sql_compatibility_value = merged_values.get("sql_target_compatibility")

    if package is not None and (not isinstance(package, str) or not package.strip()):
        raise ValueError("runner_config.json: dbt_package must be a non-empty string when provided")
    if not isinstance(logs_value, str) or not logs_value.strip():
        raise ValueError("runner_config.json: run_logs_dir must be a non-empty path")
    if (
        not isinstance(materializations, list)
        or not materializations
        or any(not isinstance(value, str) or not value.strip() for value in materializations)
    ):
        raise ValueError("runner_config.json: safe_materializations must be a non-empty list of names")

    logs_path = Path(logs_value).expanduser()
    if not logs_path.is_absolute():
        logs_path = PROJECT_ROOT / logs_path

    return RunnerConfig(
        dbt_package=package.strip() if isinstance(package, str) else None,
        run_logs_dir=logs_path.resolve(),
        safe_materializations=tuple(value.strip().lower() for value in materializations),
        config_path=config_path,
        verify_rerun=verify_rerun,
        reuse_environment=reuse_env,
        timeout_seconds=timeout_seconds,
        compile_only=compile_only,
        project_dir=resolved_proj_dir,
        database_path=database_path,
        data_dir=data_dir,
        execution_mode=execution_mode,
        full_refresh=full_refresh,
        select=select,
        exclude=exclude,
        vars=vars_config,
        target_database=target_database,
        target_schema=target_schema,
        adapter_type=adapter_type,
        run_tests=run_tests,
        file_mappings=tuple(parsed_file_map),
        approved_sql_scripts=approved_sql_scripts,
        sql_target_compatibility=str(sql_compatibility_value).strip() if sql_compatibility_value else None,
        attachments=tuple(parsed_attachments),
        catalog_mappings=tuple(parsed_cat_map),
        schema_mappings=tuple(parsed_sch_map),
    )
