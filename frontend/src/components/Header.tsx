import React from 'react'
import { Database, Play, History, Container } from 'lucide-react'

interface HeaderProps {
  onNewRun: () => void
  onToggleHistory: () => void
  showHistory: boolean
  onToggleContainers: () => void
  showContainers: boolean
}

export const Header: React.FC<HeaderProps> = ({
  onNewRun,
  onToggleHistory,
  showHistory,
  onToggleContainers,
  showContainers,
}) => {
  return (
    <header className="border-b border-[#30363d] bg-[#161b22] px-6 py-4 sticky top-0 z-30 shadow-md">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        <div className="flex items-center space-x-3 cursor-pointer" onClick={onNewRun}>
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-500 to-orange-600 flex items-center justify-center shadow-lg shadow-orange-950/40">
            <Database className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white tracking-tight">dbt Runner</h1>
            <p className="text-xs text-gray-400">DuckDB & DuckLake Sandbox</p>
          </div>
        </div>

        <div className="flex items-center space-x-3">

          <button
            onClick={onToggleContainers}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${
              showContainers
                ? 'bg-orange-500/20 border-orange-500/40 text-orange-300'
                : 'bg-[#21262d] border-[#30363d] text-gray-300 hover:bg-[#30363d]'
            }`}
          >
            <Container className="w-3.5 h-3.5" />
            <span>Containers</span>
          </button>

          <button
            onClick={onToggleHistory}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${
              showHistory
                ? 'bg-orange-500/20 border-orange-500/40 text-orange-300'
                : 'bg-[#21262d] border-[#30363d] text-gray-300 hover:bg-[#30363d]'
            }`}
          >
            <History className="w-3.5 h-3.5" />
            <span>Past Runs</span>
          </button>

          <button
            onClick={onNewRun}
            className="flex items-center space-x-2 px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-orange-500 to-amber-600 text-white text-xs font-semibold hover:from-orange-600 hover:to-amber-700 shadow-md shadow-orange-900/30 transition-all active:scale-95"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>New Run</span>
          </button>
        </div>
      </div>
    </header>
  )
}
