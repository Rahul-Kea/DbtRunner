from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepResult:
    name: str
    command: list[str]
    return_code: int | None = None
    status: str = "not_started"
    duration_seconds: float = 0.0
    error: str | None = None



@dataclass
class RunReport:
    run_id: str
    started_at: str
    finished_at: str = ""
    project_dir: str = ""
    data_location: str = ""
    ducklake_metadata_location: str = ""
    overall_status: str = "running"
    steps: list[StepResult] = field(default_factory=list)
    model_test_results: list[dict[str, object]] = field(default_factory=list)
    model_executions: list[dict[str, object]] = field(default_factory=list)
    log_file: str = ""
    structured_log_file: str = ""
    report_file: str = ""
    config_file: str = ""
    rerun_policy: str = "isolated clone of the source DuckLake catalog per run"
    sandbox_workspace: str = ""
    sandbox_cleanup_status: str = "pending"
    object_validation: dict[str, object] = field(default_factory=dict)
    dag_validation: dict[str, object] = field(default_factory=dict)
    rerun_verification: dict[str, object] = field(default_factory=dict)
    database_type: str = "ducklake"
    execution_mode: str = "full"
    failure_details: list[str] = field(default_factory=list)
    warning_details: list[str] = field(default_factory=list)
