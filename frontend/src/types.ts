export interface StepResult {
  name: string
  command: string[]
  return_code: number | null
  status: 'pending' | 'not_started' | 'running' | 'passed' | 'failed' | 'skipped'
  duration_seconds: number
  error: string | null
}

export type StageStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped' | 'needs_configuration'
export type DiagnosticCategory = 'ConfigurationError' | 'CompilationError' | 'MissingSourceData' | 'LocationMismatch' | 'ExecutionError' | 'TestFailure'

export interface PipelineStage {
  stage_id: string
  status: StageStatus
  summary: string
  details: Record<string, any>
  remediation?: { action: string; message: string; options?: Array<Record<string, any>> } | null
}

export interface Diagnostic {
  category: DiagnosticCategory
  message: string
  stage_id: string
  details?: Record<string, any>
  next_action: string
}

export interface PipelineRemediation {
  file_mappings: Record<string, { database: string; schema: string; table: string }>
  approved_sql_scripts: string[]
  sql_target_compatibility?: string
  target_database?: string
  target_schema?: string
}

export interface ModelExecution {
  model: string
  resource_type: string
  object_type: string
  execution_status: string
  duration_seconds: number
  relation_name?: string
  error_message?: string
  is_warning?: boolean
}

export interface ColumnInfo {
  name: string
  data_type: string
}

export interface DatabaseObject {
  database: string
  schema: string
  name: string
  relation_type: string
  columns: ColumnInfo[]
  row_count?: number | null
  sample_columns?: string[]
  sample_rows?: Record<string, any>[]
}

export interface TablePreviewResponse {
  status: string
  run_id: string
  database?: string
  schema?: string
  table: string
  row_count?: number | null
  columns: string[]
  rows: Record<string, any>[]
  refreshed_at: string
  message?: string
}

export interface ObjectValidation {
  status: string
  actual_objects?: DatabaseObject[]
  failures?: string[]
}

export interface DagValidation {
  status: string
  models_count?: number
  seeds_count?: number
  snapshots_count?: number
  tests_count?: number
  sources_count?: number
  models_by_materialization?: Record<string, number>
  failures?: string[]
}

export interface RerunVerification {
  status: string
  duration_seconds?: number
  message?: string
}

export interface IngestedTable {
  table_name: string
  source_file: string
  row_count: number
  columns: Array<{ name: string; type: string }>
}

export interface IncrementalModelInfo {
  unique_id: string
  name: string
  alias?: string
  database?: string
  schema?: string
  materialized: 'incremental'
  description?: string
  package_name?: string
  execution_status?: string
}

export interface RunReport {
  run_id: string
  session_id?: string
  started_at: string
  finished_at: string
  project_dir: string
  data_location: string
  ducklake_metadata_location: string
  overall_status: 'running' | 'passed' | 'failed' | 'needs_configuration' | 'cancelled' | 'unknown'
  database_type: string
  execution_mode?: 'build' | 'run' | 'compile' | 'compile_only' | 'full' | string
  full_refresh?: boolean
  select?: string | null
  incremental_models?: IncrementalModelInfo[]
  container_destroyed?: boolean
  ingested_tables?: IngestedTable[]
  steps: StepResult[]
  model_test_results: ModelExecution[]
  model_executions: ModelExecution[]
  log_file: string
  structured_log_file: string
  report_file: string
  config_file: string
  rerun_policy: string
  sandbox_workspace?: string
  sandbox_cleanup_status: string
  object_validation: ObjectValidation
  dag_validation: DagValidation
  rerun_verification: RerunVerification
  failure_details: string[]
  warning_details: string[]
  pipeline_stages?: PipelineStage[]
  diagnostics?: Diagnostic[]
  next_action?: string
  effective_target_config?: Record<string, any>
  project_manifest?: Record<string, any>
  artifact_snapshots?: Record<string, any>
}

export interface RunSummary {
  run_id: string
  status: string
  started_at: string
  finished_at: string
  project_name: string
  database_type: string
  steps_count?: number
  models_count?: number
  execution_mode?: string
  full_refresh?: boolean
  select?: string | null
}
