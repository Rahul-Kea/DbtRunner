import React, { useState } from 'react'
import {
  CheckCircle2,
  XCircle,
  Clock,
  Terminal,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import type { StepResult } from '../types'

interface PipelineStepsViewProps {
  steps: StepResult[]
}

export const PipelineStepsView: React.FC<PipelineStepsViewProps> = ({ steps }) => {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)

  if (!steps || steps.length === 0) {
    return (
      <div className="p-8 text-center text-gray-500 rounded-2xl bg-[#161b22] border border-[#30363d]">
        <Clock className="w-8 h-8 mx-auto mb-2 text-gray-600 animate-spin" />
        <p className="text-sm">Sandbox pipeline initializing...</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {steps.map((step, idx) => {
        const isPassed = step.status === 'passed'
        const isFailed = step.status === 'failed'
        const isRunning = step.status === 'running'
        const isExpanded = expandedIndex === idx

        return (
          <div
            key={idx}
            className={`rounded-xl border transition-all ${
              isRunning
                ? 'bg-amber-950/10 border-amber-500/40 shadow-md shadow-amber-950/10'
                : isFailed
                ? 'bg-rose-950/10 border-rose-500/40'
                : 'bg-[#161b22] border-[#30363d] hover:border-gray-600'
            }`}
          >
            <div
              onClick={() => setExpandedIndex(isExpanded ? null : idx)}
              className="p-4 flex items-center justify-between cursor-pointer select-none"
            >
              <div className="flex items-center space-x-3">
                {isRunning ? (
                  <Clock className="w-5 h-5 text-amber-400 animate-spin" />
                ) : isPassed ? (
                  <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                ) : isFailed ? (
                  <XCircle className="w-5 h-5 text-rose-400" />
                ) : (
                  <div className="w-5 h-5 rounded-full border border-gray-600" />
                )}

                <div>
                  <h4 className="text-sm font-semibold text-white flex items-center space-x-2">
                    <span>{step.name}</span>
                    <span
                      className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${
                        isPassed
                          ? 'bg-emerald-500/20 text-emerald-300'
                          : isFailed
                          ? 'bg-rose-500/20 text-rose-300'
                          : isRunning
                          ? 'bg-amber-500/20 text-amber-300 animate-pulse'
                          : 'bg-gray-800 text-gray-400'
                      }`}
                    >
                      {step.status}
                    </span>
                  </h4>
                  {step.error && (
                    <p className="text-xs text-rose-300 mt-1 font-mono">{step.error}</p>
                  )}
                </div>
              </div>

              <div className="flex items-center space-x-4">
                <span className="text-xs text-gray-400 font-mono">
                  {step.duration_seconds > 0 ? `${step.duration_seconds.toFixed(2)}s` : ''}
                </span>
                {step.return_code !== null && (
                  <span
                    className={`text-[11px] font-mono px-2 py-0.5 rounded border ${
                      step.return_code === 0
                        ? 'border-emerald-500/30 text-emerald-400 bg-emerald-500/5'
                        : 'border-rose-500/30 text-rose-400 bg-rose-500/5'
                    }`}
                  >
                    exit {step.return_code}
                  </span>
                )}
                {isExpanded ? (
                  <ChevronDown className="w-4 h-4 text-gray-400" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-gray-400" />
                )}
              </div>
            </div>

            {isExpanded && step.command && step.command.length > 0 && (
              <div className="px-4 pb-4 border-t border-[#30363d]/50 pt-3">
                <div className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1 flex items-center space-x-1">
                  <Terminal className="w-3.5 h-3.5" />
                  <span>Subprocess Command</span>
                </div>
                <div className="p-2.5 rounded-lg bg-[#0d1117] border border-[#30363d] font-mono text-xs text-orange-300 overflow-x-auto">
                  $ {step.command.join(' ')}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
