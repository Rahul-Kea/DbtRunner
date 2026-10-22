from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


SUPPORTED_INPUT_SUFFIXES = {".csv", ".parquet", ".json", ".ndjson", ".sql"}
RESOURCE_PATH_KEYS = {
    "models": "model-paths",
    "seeds": "seed-paths",
    "snapshots": "snapshot-paths",
    "macros": "macro-paths",
    "tests": "test-paths",
}


@dataclass
class ProjectManifest:
    project_dir: str
    project_file: str
    name: str
    version: str
    profile: str
    paths: dict[str, list[str]] = field(default_factory=dict)
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    dependency_files: list[str] = field(default_factory=list)
    declared_sources: list[dict[str, Any]] = field(default_factory=list)
    schema_database_macros: list[str] = field(default_factory=list)
    bundled_profiles: dict[str, Any] = field(default_factory=dict)
    candidate_inputs: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectInspector:
    """Inspect a dbt project without parsing SQL or assuming resource directories."""

    def inspect(self, project_dir: Path) -> ProjectManifest:
        root = project_dir.resolve()
        project_file = root / "dbt_project.yml"
        if not project_file.is_file():
            raise ValueError(f"No dbt_project.yml found in {root}")
        config = yaml.safe_load(project_file.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError(f"Expected {project_file} to contain a YAML mapping")

        paths: dict[str, list[str]] = {}
        resources: dict[str, dict[str, Any]] = {}
        for kind, key in RESOURCE_PATH_KEYS.items():
            configured = config.get(key, [kind])
            if isinstance(configured, str):
                configured = [configured]
            if not isinstance(configured, list):
                configured = [kind]
            clean_paths = [str(p) for p in configured if isinstance(p, str) and p.strip()]
            paths[kind] = clean_paths
            files: list[str] = []
            present = False
            for relative in clean_paths:
                location = (root / relative).resolve()
                if location == root or root not in location.parents:
                    raise ValueError(f"Configured {kind} path escapes the project: {relative}")
                if location.is_dir():
                    present = True
                    files.extend(str(p.relative_to(root)) for p in sorted(location.rglob("*")) if p.is_file())
            resources[kind] = {"present": present, "files": files, "file_count": len(files)}

        dependency_files: list[str] = []
        for name in ("packages.yml", "dependencies.yml", "requirements.txt", "pyproject.toml"):
            path = root / name
            if path.is_file():
                dependency_files.append(name)

        sources = self._declared_sources(root, paths["models"])
        macros = []
        for macro_path in paths["macros"]:
            directory = root / macro_path
            if directory.is_dir():
                macros.extend(
                    str(path.relative_to(root)) for path in directory.rglob("*.sql")
                    if path.stem in {"generate_schema_name", "generate_database_name"}
                )

        profiles_path = root / "profiles.yml"
        profiles: dict[str, Any] = {}
        if profiles_path.is_file():
            payload = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                profiles = payload

        resource_roots = [
            (root / relative).resolve()
            for values in paths.values() for relative in values
        ]
        candidate_inputs: list[dict[str, str]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
                continue
            relative = path.relative_to(root)
            if any(path.resolve() == resource or resource in path.resolve().parents for resource in resource_roots):
                continue
            if any(part.startswith(".") or part in {"target", "dbt_packages", "logs"} for part in relative.parts):
                continue
            candidate_inputs.append({"path": str(relative), "kind": "sql_setup" if path.suffix.lower() == ".sql" else "external_file"})

        return ProjectManifest(
            project_dir=str(root), project_file=str(project_file),
            name=str(config.get("name") or ""), version=str(config.get("version") or ""),
            profile=str(config.get("profile") or ""), paths=paths, resources=resources,
            dependency_files=dependency_files, declared_sources=sources,
            schema_database_macros=macros, bundled_profiles=profiles,
            candidate_inputs=candidate_inputs,
        )

    @staticmethod
    def _declared_sources(root: Path, model_paths: list[str]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for model_path in model_paths:
            directory = root / model_path
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*.yml")) + sorted(directory.rglob("*.yaml")):
                try:
                    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                except (OSError, yaml.YAMLError):
                    continue
                if not isinstance(payload, dict):
                    continue
                for source_group in payload.get("sources", []) or []:
                    if not isinstance(source_group, dict):
                        continue
                    for table in source_group.get("tables", []) or []:
                        if isinstance(table, dict):
                            sources.append({
                                "source_name": source_group.get("name"),
                                "name": table.get("name"),
                                "identifier": table.get("identifier") or table.get("name"),
                                "database": table.get("database", source_group.get("database")),
                                "schema": table.get("schema", source_group.get("schema")),
                                "file": str(path.relative_to(root)),
                            })
        return sources


def has_nonempty_dbt_dependencies(project_dir: Path) -> bool:
    for name in ("packages.yml", "dependencies.yml"):
        path = project_dir / name
        if not path.is_file():
            continue
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            return True  # Let native `dbt deps` report malformed configuration.
        if isinstance(payload, dict) and payload.get("packages"):
            return True
        if isinstance(payload, list) and payload:
            return True
    return False
