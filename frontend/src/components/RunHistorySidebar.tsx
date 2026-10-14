import React from 'react'
import {
  X,
  History,
  CheckCircle2,
  XCircle,
  Clock,
  RefreshCw,
} from 'lucide-react'
import type { RunSummary } from '../types'

interface RunHistorySidebarProps {
  isOpen: boolean
  onClose: () => void
  runs: RunSummary[]
  activeRunId: string | null
  onSelectRun: (runId: string) => void
  onRefresh: () => void
  isLoading: boolean
}

export const RunHistorySidebar: React.FC<RunHistorySidebarProps> = ({
  isOpen,
  onClose,
  runs,
  activeRunId,
  onSelectRun,
  onRefresh,
  isLoading,
}) => {
  if (!isOpen) return null

  const formatTimestamp = (isoString?: string) => {
    if (!isoString) return ''
    try {
      const date = new Date(isoString)
      return date.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      return isoString
    }
  }

  return (
    <div className="fixed inset-y-0 right-0 w-80 sm:w-96 bg-[#161b22] border-l border-[#30363d] shadow-2xl z-40 flex flex-col animate-in slide-in-from-right duration-200">
      {/* Drawer Header */}
      <div className="p-4 border-b border-[#30363d] flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <History className="w-4 h-4 text-orange-400" />
          <h3 className="font-bold text-white text-sm">Execution History</h3>
        </div>
        <div className="flex items-center space-x-2">
          <button
            onClick={onRefresh}
            className="p-1 text-gray-400 hover:text-white rounded hover:bg-[#21262d] transition-colors"
            title="Refresh runs"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin text-orange-400' : ''}`} />
          </button>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-white rounded hover:bg-[#21262d] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Runs List */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2.5">
        {runs.length === 0 ? (
          <div className="text-center py-12 text-gray-500 text-xs">
            No previous execution reports found.
          </div>
        ) : (
          runs.map((r) => {
            const isSelected = activeRunId === r.run_id
            const isPassed = r.status === 'passed'
            const isFailed = r.status === 'failed'

            return (
              <div
                key={r.run_id}
                onClick={() => {
                  onSelectRun(r.run_id)
                  onClose()
                }}
                className={`p-3.5 rounded-xl border cursor-pointer transition-all ${
                  isSelected
                    ? 'border-orange-500 bg-orange-950/20 shadow-md'
                    : 'border-[#30363d] bg-[#0d1117] hover:border-gray-600 hover:bg-[#1c2128]'
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="font-mono text-xs font-semibold text-white truncate max-w-[170px]">
                    #{r.run_id}
                  </span>
                  <span
                    className={`inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                      isPassed
                        ? 'bg-emerald-500/20 text-emerald-300'
                        : isFailed
                        ? 'bg-rose-500/20 text-rose-300'
                        : 'bg-amber-500/20 text-amber-300 animate-pulse'
                    }`}
                  >
                    {isPassed ? (
                      <CheckCircle2 className="w-3 h-3" />
                    ) : isFailed ? (
                      <XCircle className="w-3 h-3" />
                    ) : (
                      <Clock className="w-3 h-3 animate-spin" />
                    )}
                    <span>{r.status}</span>
                  </span>
                </div>

                <div className="text-xs text-gray-400 truncate mb-1">
                  Project: <span className="text-gray-200 font-medium">{r.project_name}</span>
                </div>

                <div className="flex items-center justify-between text-[11px] text-gray-500 font-mono mt-2 pt-2 border-t border-[#30363d]/40">
                  <span className="uppercase text-amber-400/80">{r.database_type || 'DUCKLAKE'}</span>
                  <span>{formatTimestamp(r.started_at)}</span>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
