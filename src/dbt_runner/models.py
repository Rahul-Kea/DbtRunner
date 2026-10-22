from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


StageStatus = Literal["pending", "running", "passed", "failed", "skipped", "needs_configuration"]
DiagnosticCategory = Literal[
    "ConfigurationError", "CompilationError", "MissingSourceData",
    "LocationMismatch", "ExecutionError", "TestFailure",
]


@dataclass
class Remediation:
    action: str
    message: str
    options: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PipelineStage:
    stage_id: str
    status: StageStatus = "pending"
    summary: str = "Waiting to start"
    details: dict[str, Any] = field(default_factory=dict)
    remediation: Remediation | None = None


@dataclass
class Diagnostic:
    category: DiagnosticCategory
    message: str
    stage_id: str
    details: dict[str, Any] = field(default_factory=dict)
    next_action: str = ""


def initial_pipeline_stages() -> list[PipelineStage]:
    return [
        PipelineStage("project_detected"),
        PipelineStage("environment_ready"),
        PipelineStage("source_data_ready"),
        PipelineStage("compilation_passed"),
        PipelineStage("models_executed"),
    ]


@dataclass
class StepResult:
    name: str
    command: list[str]
    return_code: int | None = None
    status: str = "pending"
    duration_seconds: float = 0.0
    error: str | None = None
    stdout: str = ""
    stderr: str = ""
    started_at: str = ""
    finished_at: str = ""



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
    rerun_policy: str = "isolated clone of the configured source target per run"
    sandbox_workspace: str = ""
    sandbox_cleanup_status: str = "pending"
    object_validation: dict[str, object] = field(default_factory=dict)
    dag_validation: dict[str, object] = field(default_factory=dict)
    rerun_verification: dict[str, object] = field(default_factory=dict)
    database_type: str = "unknown"
    execution_mode: str = "run"
    full_refresh: bool = False
    select: str | None = None
    incremental_models: list[dict[str, object]] = field(default_factory=list)
    failure_details: list[str] = field(default_factory=list)
    warning_details: list[str] = field(default_factory=list)
    pipeline_stages: list[PipelineStage] = field(default_factory=initial_pipeline_stages)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    project_manifest: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    artifact_snapshots: dict[str, Any] = field(default_factory=dict)
    effective_target_config: dict[str, Any] = field(default_factory=dict)
    execution_options: dict[str, Any] = field(default_factory=dict)
    next_action: str = ""
    run_tests: bool = True
