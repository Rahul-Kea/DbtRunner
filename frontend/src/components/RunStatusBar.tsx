import React from 'react'
import {
  CheckCircle2,
  XCircle,
  Clock,
  Layers,
  Terminal,
  ShieldCheck,
} from 'lucide-react'
import type { RunReport } from '../types'

interface RunStatusBarProps {
  report: RunReport | null
  activeTab: 'models' | 'steps' | 'terminal'
  onSelectTab: (tab: 'models' | 'steps' | 'terminal') => void
  isStreaming: boolean
}

export const RunStatusBar: React.FC<RunStatusBarProps> = ({
  report,
  activeTab,
  onSelectTab,
  isStreaming,
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
              {report.execution_mode === 'compile_only' && (
                <span className="px-2 py-0.5 rounded-md text-xs font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30 uppercase">
                  Dry Run (Compile Only)
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
  )
}
