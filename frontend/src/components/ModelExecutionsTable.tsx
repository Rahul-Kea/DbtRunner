import React, { useState } from 'react'
import {
  CheckCircle2,
  XCircle,
  Search,
  FileCode,
  Layers,
  Database,
  ShieldCheck,
  Eye,
  RotateCw,
  X,
  TableProperties,
  AlertCircle,
  AlertTriangle,
} from 'lucide-react'
import type { ModelExecution, ObjectValidation, TablePreviewResponse } from '../types'

interface ModelExecutionsTableProps {
  executions: ModelExecution[]
  runId?: string | null
  objectValidation?: ObjectValidation
  failures?: string[]
  warnings?: string[]
}

export const ModelExecutionsTable: React.FC<ModelExecutionsTableProps> = ({
  executions,
  runId,
  objectValidation,
  failures,
  warnings,
}) => {
  const [filterQuery, setFilterQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'success' | 'error'>('all')

  // Sample Rows Modal state
  const [activePreviewModel, setActivePreviewModel] = useState<string | null>(null)
  const [previewData, setPreviewData] = useState<TablePreviewResponse | null>(null)
  const [isPreviewLoading, setIsPreviewLoading] = useState<boolean>(false)

  const filtered = (executions || []).filter((exec) => {
    const matchesQuery =
      exec.model.toLowerCase().includes(filterQuery.toLowerCase()) ||
      (exec.relation_name && exec.relation_name.toLowerCase().includes(filterQuery.toLowerCase()))
    const isError =
      exec.execution_status?.toLowerCase().includes('error') ||
      exec.execution_status?.toLowerCase().includes('fail')
    if (statusFilter === 'error') return matchesQuery && isError
    if (statusFilter === 'success') return matchesQuery && !isError
    return matchesQuery
  })

  const getResourceIcon = (type: string) => {
    switch (type) {
      case 'seed':
        return <Layers className="w-4 h-4 text-amber-400" />
      case 'snapshot':
        return <Database className="w-4 h-4 text-blue-400" />
      case 'test':
        return <ShieldCheck className="w-4 h-4 text-emerald-400" />
      default:
        return <FileCode className="w-4 h-4 text-orange-400" />
    }
  }

  const handleOpenPreview = async (modelName: string) => {
    setActivePreviewModel(modelName)
    setIsPreviewLoading(true)

    // Check cached actual_objects first for instant display
    const matchedObj = objectValidation?.actual_objects?.find(
      (o) => o.name.toLowerCase() === modelName.toLowerCase()
    )

    if (matchedObj && matchedObj.sample_rows && matchedObj.sample_rows.length > 0) {
      setPreviewData({
        status: 'success',
        run_id: runId || '',
        database: matchedObj.database,
        schema: matchedObj.schema,
        table: matchedObj.name,
        row_count: matchedObj.row_count,
        columns:
          matchedObj.sample_columns ||
          matchedObj.columns?.map((c) => c.name) ||
          [],
        rows: matchedObj.sample_rows,
        refreshed_at: new Date().toISOString(),
      })
    } else {
      setPreviewData(null)
    }

    // Then fetch fresh data from backend if runId exists
    if (runId) {
      try {
        const res = await fetch(
          `/api/runs/${runId}/preview?table=${encodeURIComponent(modelName)}&limit=25`
        )
        if (res.ok) {
          const data: TablePreviewResponse = await res.json()
          if (data.status === 'success') {
            setPreviewData(data)
          }
        }
      } catch (err) {
        console.error('Failed to fetch preview for model:', err)
      } finally {
        setIsPreviewLoading(false)
      }
    } else {
      setIsPreviewLoading(false)
    }
  }

  const handleRefreshPreview = async () => {
    if (!activePreviewModel || !runId) return
    setIsPreviewLoading(true)
    try {
      const res = await fetch(
        `/api/runs/${runId}/preview?table=${encodeURIComponent(activePreviewModel)}&limit=25`
      )
      if (res.ok) {
        const data: TablePreviewResponse = await res.json()
        setPreviewData(data)
      }
    } catch (err) {
      console.error('Failed to refresh preview:', err)
    } finally {
      setIsPreviewLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Execution Failures Alert Banner */}
      {failures && failures.length > 0 && (
        <div className="p-4 rounded-2xl bg-rose-950/20 border border-rose-500/40 text-rose-200 space-y-2 shadow-sm">
          <div className="flex items-center space-x-2 text-rose-300 font-semibold text-xs">
            <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <span>Execution Failures ({failures.length})</span>
          </div>
          <div className="space-y-1 font-mono text-xs max-h-40 overflow-y-auto">
            {failures.map((f, i) => (
              <div key={i} className="p-2 rounded-lg bg-[#0d1117] border border-rose-500/20 leading-relaxed">
                {f}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Warnings Banner */}
      {warnings && warnings.length > 0 && (
        <div className="p-4 rounded-2xl bg-amber-950/20 border border-amber-500/40 text-amber-200 space-y-2 shadow-sm">
          <div className="flex items-center space-x-2 text-amber-300 font-semibold text-xs">
            <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
            <span>Warnings ({warnings.length})</span>
          </div>
          <div className="space-y-1 font-mono text-xs max-h-32 overflow-y-auto">
            {warnings.map((w, i) => (
              <div key={i} className="p-2 rounded-lg bg-[#0d1117] border border-amber-500/20 leading-relaxed">
                {w}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Search and Filters */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-72">
          <Search className="w-4 h-4 absolute left-3 top-2.5 text-gray-400" />
          <input
            type="text"
            placeholder="Filter models or relations..."
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            className="w-full bg-[#161b22] border border-[#30363d] rounded-xl pl-9 pr-3 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-orange-500"
          />
        </div>

        <div className="flex items-center space-x-2">
          <button
            onClick={() => setStatusFilter('all')}
            className={`px-3 py-1 rounded-lg text-xs font-medium border transition-colors ${
              statusFilter === 'all'
                ? 'bg-orange-500/20 border-orange-500/40 text-orange-300'
                : 'bg-[#161b22] border-[#30363d] text-gray-400 hover:text-white'
            }`}
          >
            All ({executions?.length || 0})
          </button>
          <button
            onClick={() => setStatusFilter('success')}
            className={`px-3 py-1 rounded-lg text-xs font-medium border transition-colors ${
              statusFilter === 'success'
                ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300'
                : 'bg-[#161b22] border-[#30363d] text-gray-400 hover:text-white'
            }`}
          >
            Passed
          </button>
          <button
            onClick={() => setStatusFilter('error')}
            className={`px-3 py-1 rounded-lg text-xs font-medium border transition-colors ${
              statusFilter === 'error'
                ? 'bg-rose-500/20 border-rose-500/40 text-rose-300'
                : 'bg-[#161b22] border-[#30363d] text-gray-400 hover:text-white'
            }`}
          >
            Errors
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-2xl border border-[#30363d] bg-[#161b22] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-[#30363d] bg-[#0d1117] text-gray-400 font-semibold uppercase tracking-wider">
                <th className="py-3 px-4">Node / Model</th>
                <th className="py-3 px-4">Type</th>
                <th className="py-3 px-4">Materialization</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Duration</th>
                <th className="py-3 px-4">Physical Relation</th>
                <th className="py-3 px-4 text-right">Data Preview</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#30363d]/50">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-gray-500">
                    No model executions match your filter.
                  </td>
                </tr>
              ) : (
                filtered.map((item, idx) => {
                  const isError =
                    item.execution_status?.toLowerCase().includes('error') ||
                    item.execution_status?.toLowerCase().includes('fail')
                  const canPreview = !isError && item.resource_type !== 'test'

                  return (
                    <tr key={idx} className="hover:bg-[#1c2128] transition-colors">
                      <td className="py-3 px-4 font-mono font-medium text-white flex items-center space-x-2">
                        {getResourceIcon(item.resource_type)}
                        <span>{item.model}</span>
                      </td>
                      <td className="py-3 px-4 text-gray-400 uppercase text-[11px] font-semibold">
                        {item.resource_type}
                      </td>
                      <td className="py-3 px-4">
                        <span className="px-2 py-0.5 rounded bg-[#0d1117] border border-[#30363d] text-gray-300 font-mono text-[11px]">
                          {item.object_type || 'table'}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={`inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[11px] font-bold uppercase ${
                            isError
                              ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                              : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                          }`}
                        >
                          {isError ? (
                            <XCircle className="w-3 h-3" />
                          ) : (
                            <CheckCircle2 className="w-3 h-3" />
                          )}
                          <span>{item.execution_status}</span>
                        </span>
                      </td>
                      <td className="py-3 px-4 font-mono text-gray-400">
                        {item.duration_seconds ? `${item.duration_seconds.toFixed(3)}s` : '-'}
                      </td>
                      <td className="py-3 px-4 font-mono text-gray-300 text-[11px]">
                        {item.relation_name || '-'}
                        {item.error_message && (
                          <div className="mt-1 text-rose-400 font-mono text-[11px] bg-rose-950/20 p-1.5 rounded border border-rose-500/30">
                            {item.error_message}
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-4 text-right">
                        {canPreview ? (
                          <button
                            type="button"
                            onClick={() => handleOpenPreview(item.model)}
                            className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-lg bg-[#0d1117] hover:bg-[#161b22] border border-[#30363d] hover:border-orange-500/60 text-[11px] font-medium text-orange-400 hover:text-orange-300 transition-colors"
                          >
                            <Eye className="w-3 h-3" />
                            <span>Preview</span>
                          </button>
                        ) : (
                          <span className="text-gray-600 text-[11px]">-</span>
                        )}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Sample Rows Preview Modal */}
      {activePreviewModel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="bg-[#161b22] border border-[#30363d] rounded-2xl w-full max-w-4xl shadow-2xl flex flex-col max-h-[85vh] overflow-hidden">
            {/* Modal Header */}
            <div className="px-5 py-4 border-b border-[#30363d] flex items-center justify-between bg-[#0d1117]">
              <div className="flex items-center space-x-3">
                <div className="w-8 h-8 rounded-lg bg-orange-500/10 border border-orange-500/20 flex items-center justify-center text-orange-400">
                  <Database className="w-4 h-4" />
                </div>
                <div>
                  <div className="flex items-center space-x-2">
                    <h3 className="text-sm font-bold text-white font-mono">
                      {activePreviewModel}
                    </h3>
                    {previewData?.row_count !== null && previewData?.row_count !== undefined && (
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                        {previewData.row_count.toLocaleString()} rows
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-gray-400">
                    Live database sample row inspection (Top 25 rows)
                  </p>
                </div>
              </div>

              <div className="flex items-center space-x-2">
                {runId && (
                  <button
                    type="button"
                    onClick={handleRefreshPreview}
                    disabled={isPreviewLoading}
                    className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-[#161b22] hover:bg-[#21262d] border border-[#30363d] text-xs text-gray-300 hover:text-white transition-colors disabled:opacity-50"
                  >
                    <RotateCw
                      className={`w-3.5 h-3.5 text-orange-400 ${
                        isPreviewLoading ? 'animate-spin' : ''
                      }`}
                    />
                    <span>{isPreviewLoading ? 'Refreshing...' : 'Refresh'}</span>
                  </button>
                )}

                <button
                  type="button"
                  onClick={() => {
                    setActivePreviewModel(null)
                    setPreviewData(null)
                  }}
                  className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-[#21262d] transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Modal Body */}
            <div className="p-5 flex-1 overflow-y-auto">
              {isPreviewLoading && !previewData ? (
                <div className="py-12 flex flex-col items-center justify-center space-y-2 text-gray-400">
                  <RotateCw className="w-6 h-6 animate-spin text-orange-400" />
                  <span className="text-xs">Querying database state...</span>
                </div>
              ) : previewData && previewData.rows && previewData.rows.length > 0 ? (
                <div className="overflow-x-auto border border-[#30363d] rounded-xl bg-[#0d1117]">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead className="sticky top-0 bg-[#161b22] border-b border-[#30363d] shadow-sm">
                      <tr>
                        <th className="px-3 py-2 text-[10px] text-gray-500 font-mono w-10 border-r border-[#30363d]/50">
                          #
                        </th>
                        {previewData.columns.map((colName) => (
                          <th
                            key={colName}
                            className="px-3 py-2 text-[11px] text-gray-300 font-mono font-semibold whitespace-nowrap"
                          >
                            {colName}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#30363d]/40">
                      {previewData.rows.map((row, rIdx) => (
                        <tr
                          key={rIdx}
                          className="hover:bg-[#1c2128] transition-colors font-mono text-[11px]"
                        >
                          <td className="px-3 py-1.5 text-gray-500 border-r border-[#30363d]/50 select-none">
                            {rIdx + 1}
                          </td>
                          {previewData.columns.map((colName) => {
                            const val = row[colName]
                            return (
                              <td
                                key={colName}
                                className="px-3 py-1.5 whitespace-nowrap text-gray-200"
                              >
                                {val === null || val === undefined ? (
                                  <span className="italic text-gray-500 text-[10px]">NULL</span>
                                ) : typeof val === 'boolean' ? (
                                  <span className="text-blue-400 font-semibold">
                                    {val ? 'true' : 'false'}
                                  </span>
                                ) : typeof val === 'number' ? (
                                  <span className="text-amber-300">{val}</span>
                                ) : (
                                  <span>{String(val)}</span>
                                )}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="py-12 text-center rounded-xl bg-[#0d1117] border border-[#30363d] space-y-1">
                  <TableProperties className="w-8 h-8 text-gray-500 mx-auto mb-2 opacity-60" />
                  <p className="text-xs text-gray-300 font-medium">
                    No sample rows found for {activePreviewModel}.
                  </p>
                  <p className="text-[11px] text-gray-500">
                    Table may be empty, or run in compilation mode without data.
                  </p>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="px-5 py-3 border-t border-[#30363d] bg-[#0d1117] flex items-center justify-between text-[11px] text-gray-400 font-mono">
              <span>
                {previewData?.rows ? `${previewData.rows.length} rows displayed` : ''}
              </span>
              <button
                type="button"
                onClick={() => {
                  setActivePreviewModel(null)
                  setPreviewData(null)
                }}
                className="px-3 py-1 rounded-lg bg-[#21262d] hover:bg-[#30363d] text-white text-xs font-medium transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
