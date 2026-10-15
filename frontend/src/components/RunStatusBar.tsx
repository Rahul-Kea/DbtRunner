import React from 'react'
import {
  CheckCircle2,
  XCircle,
  Clock,
  Layers,
  Terminal,
  ShieldCheck,
  RefreshCw,
  Play,
} from 'lucide-react'
import type { RunReport } from '../types'

interface RunStatusBarProps {
  report: RunReport | null
  activeTab: 'models' | 'steps' | 'terminal'
  onSelectTab: (tab: 'models' | 'steps' | 'terminal') => void
  isStreaming: boolean
  onTriggerRun?: (runId: string) => void
  onTriggerFullRefresh?: (runId: string) => void
  isTriggeringAction?: boolean
}

export const RunStatusBar: React.FC<RunStatusBarProps> = ({
  report,
  activeTab,
  onSelectTab,
  isStreaming,
  onTriggerRun,
  onTriggerFullRefresh,
  isTriggeringAction,
}) => {
  if (!report) return null

  const isRunning = report.overall_status === 'running' || isStreaming
  const isPassed = report.overall_status === 'passed'

  const failureCount = report.failure_details?.length || 0

  return (
    <div className="bg-[#161b22] border-b border-[#30363d] px-6 py-4">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center space-x-4">
          <div
            className={`w-12 h-12 rounded-xl flex items-center justify-center font-bold text-lg shadow-md ${
              isRunning
                ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                : isPassed
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                : 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
            }`}
          >
            {isRunning ? (
              <Clock className="w-6 h-6 animate-spin text-amber-400" />
            ) : isPassed ? (
              <CheckCircle2 className="w-6 h-6 text-emerald-400" />
            ) : (
              <XCircle className="w-6 h-6 text-rose-400" />
            )}
          </div>

          <div>
            <div className="flex items-center space-x-2">
              <span className="font-mono text-sm font-semibold text-white">
                Run #{report.run_id}
              </span>
              <span
                className={`px-2 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider ${
                  isRunning
                    ? 'bg-amber-500/20 text-amber-300 animate-pulse'
                    : isPassed
                    ? 'bg-emerald-500/20 text-emerald-300'
                    : 'bg-rose-500/20 text-rose-300'
                }`}
              >
                {report.overall_status}
              </span>
              <span className="px-2 py-0.5 rounded-md text-xs font-semibold bg-[#21262d] text-gray-300 border border-[#30363d] uppercase">
                {report.database_type || 'DUCKLAKE'}
              </span>
              {/* Execution Mode Badge */}
              <span className="px-2 py-0.5 rounded-md text-xs font-semibold bg-[#21262d] text-gray-300 border border-[#30363d] uppercase">
                {report.execution_mode === 'compile' || report.execution_mode === 'compile_only'
                  ? 'dbt compile'
                  : 'dbt run'}
              </span>

              {/* Full Refresh Badge */}
              {report.full_refresh && (
                <span className="px-2 py-0.5 rounded-md text-xs font-semibold bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 uppercase">
                  Full Refresh
                </span>
              )}

              {/* Model Select Badge */}
              {report.select && (
                <span className="px-2 py-0.5 rounded-md text-xs font-mono font-medium bg-purple-500/10 text-purple-300 border border-purple-500/30 truncate max-w-xs" title={`--select ${report.select}`}>
                  -s {report.select}
                </span>
              )}

              {failureCount > 0 && (
                <span className="px-2 py-0.5 rounded-md text-xs font-semibold bg-rose-500/20 text-rose-300 border border-rose-500/30">
                  {failureCount} {failureCount === 1 ? 'Error' : 'Errors'}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-400 mt-1 truncate max-w-xl">
              Project: <span className="text-gray-200 font-mono">{report.project_dir || 'Sandbox'}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2 flex-wrap gap-y-2">
          {/* Action: Run Pipeline (dbt run) if previous run was a compile / DAG run */}
          {!isRunning && (report.execution_mode === 'compile' || report.execution_mode === 'compile_only') && onTriggerRun && (
            <button
              type="button"
              onClick={() => onTriggerRun(report.run_id)}
              disabled={isTriggeringAction}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-orange-500 hover:bg-orange-600 text-white transition-all shadow-sm disabled:opacity-50"
              title="Execute dbt run on this validated project"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Run Pipeline (dbt run)</span>
            </button>
          )}

          {/* Action: Run Full Refresh on database matching earlier run mode */}
          {!isRunning && onTriggerFullRefresh && (
            <button
              type="button"
              onClick={() => onTriggerFullRefresh(report.run_id)}
              disabled={isTriggeringAction}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 transition-all shadow-sm disabled:opacity-50"
              title={`Execute dbt ${report.execution_mode === 'compile' || report.execution_mode === 'compile_only' ? 'compile' : 'run'} --full-refresh (matching earlier execution mode)`}
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isTriggeringAction ? 'animate-spin' : ''}`} />
              <span>
                Perform Full Refresh{' '}
                <span className="opacity-80 font-normal">
                  ({report.execution_mode === 'compile' || report.execution_mode === 'compile_only' ? 'dbt compile' : 'dbt run'})
                </span>
              </span>
            </button>
          )}

          {/* Tab Navigation (Condensed to 3 tabs) */}
          <div className="flex items-center space-x-1 bg-[#0d1117] p-1 rounded-xl border border-[#30363d] overflow-x-auto">
          <button
            onClick={() => onSelectTab('models')}
            className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === 'models'
                ? 'bg-[#21262d] text-white shadow-sm'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5 text-orange-400" />
            <span>Models & Data Preview ({report.model_executions?.length || 0})</span>
          </button>

          <button
            onClick={() => onSelectTab('steps')}
            className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === 'steps'
                ? 'bg-[#21262d] text-white shadow-sm'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            <Layers className="w-3.5 h-3.5 text-amber-400" />
            <span>Pipeline Steps ({report.steps?.length || 0})</span>
          </button>

          <button
            onClick={() => onSelectTab('terminal')}
            className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all relative ${
              activeTab === 'terminal'
                ? 'bg-[#21262d] text-white shadow-sm'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            <Terminal className="w-3.5 h-3.5 text-emerald-400" />
            <span>Live Logs</span>
            {isStreaming && (
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping absolute -top-0.5 -right-0.5" />
            )}
          </button>
        </div>
      </div>
    </div>
  </div>
  )
}
