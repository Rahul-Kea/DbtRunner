import React, { useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  Clock,
  Layers,
  RefreshCw,
  Search,
  AlertCircle,
  FileCode,
} from 'lucide-react'
import type { IncrementalModelInfo } from '../types'

interface IncrementalModelSelectorProps {
  runId: string
  onCancel: () => void
  onRunFullRefresh: (selectedModels: string[], allIncremental: boolean) => void
  isLoading: boolean
}

export const IncrementalModelSelector: React.FC<IncrementalModelSelectorProps> = ({
  runId,
  onCancel,
  onRunFullRefresh,
  isLoading,
}) => {
  const [models, setModels] = useState<IncrementalModelInfo[]>([])
  const [isFetching, setIsFetching] = useState<boolean>(true)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState<string>('')

  // 1. Fetch discovered incremental models from dbt project metadata
  useEffect(() => {
    let isMounted = true
    const fetchModels = async () => {
      setIsFetching(true)
      setFetchError(null)
      try {
        const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/incremental-models`)
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}))
          throw new Error(errData.detail || `Failed to fetch project incremental models (${res.status})`)
        }
        const data = await res.json()
        if (isMounted) {
          const discovered: IncrementalModelInfo[] = data.incremental_models || []
          setModels(discovered)
          // Default selection: empty or unselected so user explicitly chooses
          setSelectedNames(new Set())
        }
      } catch (err: any) {
        if (isMounted) {
          setFetchError(err.message || 'Error loading incremental models')
        }
      } finally {
        if (isMounted) {
          setIsFetching(false)
        }
      }
    }

    fetchModels()
    return () => {
      isMounted = false
    }
  }, [runId])

  // Filtered by search query
  const filteredModels = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return models
    return models.filter((m) => {
      const name = m.name.toLowerCase()
      const alias = (m.alias || '').toLowerCase()
      const schema = (m.schema || '').toLowerCase()
      const db = (m.database || '').toLowerCase()
      return name.includes(q) || alias.includes(q) || schema.includes(q) || db.includes(q)
    })
  }, [models, searchQuery])

  // Select All state based on filtered models
  const isAllFilteredSelected =
    filteredModels.length > 0 &&
    filteredModels.every((m) => selectedNames.has(m.name))

  const isSomeFilteredSelected =
    filteredModels.some((m) => selectedNames.has(m.name)) && !isAllFilteredSelected

  const handleToggleSelectAll = () => {
    if (isAllFilteredSelected) {
      // Deselect all currently filtered models
      setSelectedNames((prev) => {
        const next = new Set(prev)
        filteredModels.forEach((m) => next.delete(m.name))
        return next
      })
    } else {
      // Select all currently filtered models
      setSelectedNames((prev) => {
        const next = new Set(prev)
        filteredModels.forEach((m) => next.add(m.name))
        return next
      })
    }
  }

  const handleToggleModel = (name: string) => {
    setSelectedNames((prev) => {
      const next = new Set(prev)
      if (next.has(name)) {
        next.delete(name)
      } else {
        next.add(name)
      }
      return next
    })
  }

  const handleExecute = () => {
    if (selectedNames.size === 0 || isLoading) return
    const allSelected = models.length > 0 && selectedNames.size === models.length
    const modelList = Array.from(selectedNames)
    onRunFullRefresh(modelList, allSelected)
  }

  const renderStatusBadge = (status?: string) => {
    const s = (status || 'not_run').toLowerCase()
    if (s.includes('pass') || s.includes('success') || s === 'ok') {
      return (
        <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
          <CheckCircle2 className="w-3 h-3" />
          <span>passed</span>
        </span>
      )
    }
    if (s.includes('fail') || s.includes('error')) {
      return (
        <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-500/20 text-rose-300 border border-rose-500/30">
          <XCircle className="w-3 h-3" />
          <span>failed</span>
        </span>
      )
    }
    return (
      <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-gray-700/30 text-gray-400 border border-gray-600/30">
        <Clock className="w-3 h-3" />
        <span>{status || 'not run'}</span>
      </span>
    )
  }

  const isAllIncrementalSelected = models.length > 0 && selectedNames.size === models.length
  const commandPreview = isAllIncrementalSelected
    ? 'dbt run --select "config.materialized:incremental" --full-refresh'
    : selectedNames.size > 0
    ? `dbt run --select ${Array.from(selectedNames).join(' ')} --full-refresh`
    : 'Select models above to build command'

  return (
    <div className="space-y-6">
      {/* Top Header & Navigation */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-5 rounded-2xl bg-[#161b22] border border-[#30363d] shadow-sm">
        <div className="flex items-start space-x-3.5">
          <button
            type="button"
            onClick={onCancel}
            disabled={isLoading}
            className="p-2 rounded-xl bg-[#0d1117] hover:bg-[#21262d] border border-[#30363d] text-gray-300 hover:text-white transition-all disabled:opacity-50 mt-0.5"
            title="Return to previous run view"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-base font-bold text-white tracking-tight">
                Select Models for Full Refresh
              </h1>
              <span className="px-2 py-0.5 rounded-md bg-orange-500/10 border border-orange-500/30 text-orange-300 text-[11px] font-mono font-medium">
                materialized='incremental'
              </span>
            </div>
            <p className="text-xs text-gray-400 mt-1">
              Rebuild selected incremental models from scratch ignoring the <code className="text-orange-300 font-mono">is_incremental()</code> filter.
              Unselected models and pre-existing tables are preserved untouched.
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-3 self-end sm:self-center">
          <button
            type="button"
            onClick={onCancel}
            disabled={isLoading}
            className="px-4 py-2 rounded-xl border border-[#30363d] bg-[#0d1117] hover:bg-[#21262d] text-xs font-semibold text-gray-300 hover:text-white transition-all disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleExecute}
            disabled={selectedNames.size === 0 || isLoading}
            className="flex items-center space-x-2 px-5 py-2 rounded-xl bg-orange-500 hover:bg-orange-600 disabled:bg-gray-700 text-white text-xs font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-md hover:shadow-orange-500/20"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>
              {isLoading
                ? 'Starting Refresh…'
                : selectedNames.size === 0
                ? 'Select Models'
                : isAllIncrementalSelected
                ? `Full Refresh All (${models.length})`
                : `Run Full Refresh (${selectedNames.size})`}
            </span>
          </button>
        </div>
      </div>

      {/* Loading State */}
      {isFetching && (
        <div className="p-12 rounded-2xl bg-[#161b22] border border-[#30363d] flex flex-col items-center justify-center space-y-3 text-center">
          <Clock className="w-6 h-6 animate-spin text-orange-400" />
          <div className="text-xs text-gray-300 font-medium">
            Discovering incremental models from dbt project metadata…
          </div>
          <div className="text-[11px] text-gray-500 font-mono">
            Parsing manifest nodes where config.materialized == 'incremental'
          </div>
        </div>
      )}

      {/* Error State */}
      {!isFetching && fetchError && (
        <div className="p-6 rounded-2xl bg-rose-950/20 border border-rose-500/40 text-rose-200 space-y-3">
          <div className="flex items-center space-x-2 text-rose-300 font-semibold text-xs">
            <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <span>Could not retrieve project metadata</span>
          </div>
          <p className="text-xs font-mono">{fetchError}</p>
          <button
            type="button"
            onClick={onCancel}
            className="px-3.5 py-1.5 rounded-lg bg-[#0d1117] border border-rose-500/30 text-rose-300 hover:text-white text-xs font-medium"
          >
            Return to Run View
          </button>
        </div>
      )}

      {/* Empty State: No incremental models in project */}
      {!isFetching && !fetchError && models.length === 0 && (
        <div className="p-12 rounded-2xl bg-[#161b22] border border-[#30363d] flex flex-col items-center justify-center space-y-4 text-center max-w-2xl mx-auto shadow-sm">
          <div className="w-12 h-12 rounded-2xl bg-orange-500/10 border border-orange-500/20 flex items-center justify-center text-orange-400">
            <Layers className="w-6 h-6" />
          </div>
          <div className="space-y-1">
            <h3 className="text-sm font-bold text-white">No Incremental Models Found</h3>
            <p className="text-xs text-gray-400 max-w-md leading-relaxed">
              This dbt project does not contain any models configured with{' '}
              <code className="text-orange-300 font-mono">materialized='incremental'</code> in its models or{' '}
              <code className="text-gray-300 font-mono">dbt_project.yml</code>.
            </p>
          </div>
          <div className="p-3 rounded-xl bg-[#0d1117] border border-[#30363d] text-[11px] text-gray-400 max-w-lg text-left font-mono">
            💡 To configure an incremental model in dbt, include:
            <pre className="text-gray-300 mt-1">
              {"{{ config(materialized='incremental', unique_key='id') }}"}
            </pre>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="flex items-center space-x-2 px-5 py-2 rounded-xl bg-[#0d1117] hover:bg-[#21262d] border border-[#30363d] text-white text-xs font-semibold transition-all"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Return to Run Overview</span>
          </button>
        </div>
      )}

      {/* Main Selection Table */}
      {!isFetching && !fetchError && models.length > 0 && (
        <div className="space-y-4">
          {/* Controls Bar */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 p-4 rounded-xl bg-[#161b22] border border-[#30363d]">
            <div className="flex items-center space-x-3">
              <label className="flex items-center space-x-2.5 cursor-pointer select-none text-xs font-semibold text-gray-200">
                <input
                  type="checkbox"
                  checked={isAllFilteredSelected}
                  ref={(input) => {
                    if (input) input.indeterminate = isSomeFilteredSelected
                  }}
                  onChange={handleToggleSelectAll}
                  className="rounded border-[#30363d] text-orange-500 focus:ring-0 bg-[#0d1117] w-4 h-4 cursor-pointer"
                />
                <span>Select All ({filteredModels.length})</span>
              </label>

              <span className="text-gray-600">|</span>

              <span className="text-xs text-gray-400 font-mono">
                <strong className="text-orange-400">{selectedNames.size}</strong> of {models.length} selected
              </span>
            </div>

            <div className="relative w-full sm:w-64">
              <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-gray-500" />
              <input
                type="text"
                placeholder="Filter incremental models..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-[#0d1117] border border-[#30363d] rounded-lg pl-9 pr-3 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-orange-500 font-mono"
              />
            </div>
          </div>

          {/* Model Table */}
          <div className="rounded-2xl border border-[#30363d] bg-[#161b22] overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-[#30363d] bg-[#0d1117] text-gray-400 font-semibold uppercase tracking-wider text-[11px]">
                    <th className="py-3 px-4 w-12 text-center">
                      <span className="sr-only">Select</span>
                    </th>
                    <th className="py-3 px-4">Model Name</th>
                    <th className="py-3 px-4">Schema</th>
                    <th className="py-3 px-4">Database</th>
                    <th className="py-3 px-4">Configured Materialization</th>
                    <th className="py-3 px-4">Last Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#30363d]/50">
                  {filteredModels.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="py-8 text-center text-gray-500">
                        No incremental models match your filter query.
                      </td>
                    </tr>
                  ) : (
                    filteredModels.map((item) => {
                      const isSelected = selectedNames.has(item.name)
                      return (
                        <tr
                          key={item.unique_id || item.name}
                          onClick={() => handleToggleModel(item.name)}
                          className={`cursor-pointer transition-colors ${
                            isSelected
                              ? 'bg-orange-500/10 hover:bg-orange-500/15'
                              : 'hover:bg-[#1c2128]'
                          }`}
                        >
                          <td className="py-3 px-4 text-center" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => handleToggleModel(item.name)}
                              className="rounded border-[#30363d] text-orange-500 focus:ring-0 bg-[#0d1117] w-4 h-4 cursor-pointer"
                            />
                          </td>
                          <td className="py-3 px-4 font-mono font-medium text-white flex items-center space-x-2">
                            <FileCode className="w-4 h-4 text-orange-400 shrink-0" />
                            <div className="flex flex-col">
                              <span className="font-semibold text-gray-100">{item.name}</span>
                              {item.alias && item.alias !== item.name && (
                                <span className="text-[10px] text-gray-500 font-mono">alias: {item.alias}</span>
                              )}
                            </div>
                          </td>
                          <td className="py-3 px-4 font-mono text-gray-300 text-[11px]">
                            {item.schema || '—'}
                          </td>
                          <td className="py-3 px-4 font-mono text-gray-400 text-[11px]">
                            {item.database || '—'}
                          </td>
                          <td className="py-3 px-4">
                            <span className="px-2 py-0.5 rounded-md bg-[#0d1117] border border-[#30363d] text-orange-300 font-mono text-[11px] font-medium">
                              incremental
                            </span>
                          </td>
                          <td className="py-3 px-4">
                            {renderStatusBadge(item.execution_status)}
                          </td>
                        </tr>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Command Preview Footer */}
          <div className="p-4 rounded-xl bg-[#090c10] border border-[#30363d] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 font-mono text-xs">
            <div className="flex items-center space-x-2 truncate min-w-0">
              <span className="text-gray-500 shrink-0">Command:</span>
              <span className="text-emerald-400 font-semibold truncate select-all">
                $ {commandPreview}
              </span>
            </div>
            <div className="flex items-center space-x-3 shrink-0 self-end sm:self-center">
              <span className="text-[11px] text-gray-500">
                {selectedNames.size} model{selectedNames.size === 1 ? '' : 's'} targeted
              </span>
              <button
                type="button"
                onClick={handleExecute}
                disabled={selectedNames.size === 0 || isLoading}
                className="flex items-center space-x-1.5 px-4 py-1.5 rounded-lg bg-orange-500 hover:bg-orange-600 disabled:bg-gray-800 text-white text-xs font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
              >
                <RefreshCw className={`w-3 h-3 ${isLoading ? 'animate-spin' : ''}`} />
                <span>Execute Full Refresh</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
