import React, { useEffect, useRef, useState } from 'react'
import {
  Terminal,
  Search,
  Copy,
  Check,
  Download,
  Clock,
} from 'lucide-react'

interface TerminalLogViewProps {
  logs: string[]
  isStreaming: boolean
  runId?: string
}

export const TerminalLogView: React.FC<TerminalLogViewProps> = ({
  logs,
  isStreaming,
  runId,
}) => {
  const [filter, setFilter] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [copied, setCopied] = useState(false)
  const logContainerRef = useRef<HTMLDivElement>(null)

  const filteredLogs = filter
    ? logs.filter((l) => l.toLowerCase().includes(filter.toLowerCase()))
    : logs

  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  const handleCopy = () => {
    navigator.clipboard.writeText(logs.join('\n'))
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownload = () => {
    const blob = new Blob([logs.join('\n')], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `run_${runId || 'execution'}.log`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="rounded-2xl border border-[#30363d] bg-[#0d1117] overflow-hidden flex flex-col h-[650px] shadow-2xl">
      {/* Terminal Toolbar */}
      <div className="p-3 border-b border-[#30363d] bg-[#161b22] flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-3">
          <div className="flex space-x-1.5">
            <div className="w-3 h-3 rounded-full bg-rose-500/80" />
            <div className="w-3 h-3 rounded-full bg-amber-500/80" />
            <div className="w-3 h-3 rounded-full bg-emerald-500/80" />
          </div>
          <div className="flex items-center space-x-2 text-xs font-mono text-gray-300">
            <Terminal className="w-3.5 h-3.5 text-orange-400" />
            <span>Execution Terminal Stream</span>
            {isStreaming && (
              <span className="flex items-center space-x-1 text-amber-400 text-[11px] font-semibold animate-pulse">
                <span className="w-2 h-2 rounded-full bg-amber-400" />
                <span>STREAMING</span>
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center space-x-3">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-2 text-gray-500" />
            <input
              type="text"
              placeholder="Search terminal logs..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="bg-[#0d1117] border border-[#30363d] rounded-lg pl-8 pr-2.5 py-1 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-orange-500 w-48"
            />
          </div>

          <label className="flex items-center space-x-1.5 text-xs text-gray-300 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded border-[#30363d] text-orange-500 bg-[#0d1117]"
            />
            <span>Auto-scroll</span>
          </label>

          <button
            onClick={handleCopy}
            className="flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-[#21262d] border border-[#30363d] text-xs text-gray-300 hover:text-white hover:bg-[#30363d] transition-colors"
            title="Copy logs to clipboard"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Copied' : 'Copy'}</span>
          </button>

          <button
            onClick={handleDownload}
            className="flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-[#21262d] border border-[#30363d] text-xs text-gray-300 hover:text-white hover:bg-[#30363d] transition-colors"
            title="Download log file"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export</span>
          </button>
        </div>
      </div>

      {/* Terminal Output */}
      <div
        ref={logContainerRef}
        className="flex-1 p-4 font-mono text-xs overflow-y-auto space-y-0.5 select-text"
      >
        {filteredLogs.length === 0 ? (
          <div className="h-full flex items-center justify-center text-gray-500">
            {isStreaming ? (
              <div className="flex items-center space-x-2">
                <Clock className="w-4 h-4 animate-spin text-orange-400" />
                <span>Waiting for dbt process output...</span>
              </div>
            ) : (
              <span>No logs available</span>
            )}
          </div>
        ) : (
          filteredLogs.map((line, idx) => {
            let color = 'text-gray-300'
            if (line.startsWith('$')) color = 'text-orange-400 font-bold'
            else if (line.includes('ERROR') || line.includes('Fail') || line.includes('Error')) color = 'text-rose-400 font-semibold'
            else if (line.includes('WARN')) color = 'text-amber-300'
            else if (line.includes('PASS') || line.includes('OK') || line.includes('Completed successfully')) color = 'text-emerald-400'
            else if (line.startsWith('---')) color = 'text-cyan-400 font-bold'

            return (
              <div key={idx} className={`${color} leading-relaxed whitespace-pre-wrap break-all hover:bg-white/5 px-1 rounded`}>
                {line}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
