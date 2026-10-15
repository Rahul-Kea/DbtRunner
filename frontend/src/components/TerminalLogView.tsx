import React, { useEffect, useRef, useState } from 'react'
import {
  Terminal,
  Search,
  Copy,
  Check,
  Download,
  Clock,
  Trash2,
} from 'lucide-react'

interface TerminalLogViewProps {
  logs: string[]
  isStreaming: boolean
  runId?: string
  shellToken?: string
  runStatus?: string
  containerDestroyed?: boolean
  isDestroyingContainer?: boolean
  onDestroyContainer?: () => void
}

export const TerminalLogView: React.FC<TerminalLogViewProps> = ({
  logs,
  isStreaming,
  runId,
  shellToken,
  runStatus,
  containerDestroyed = false,
  isDestroyingContainer = false,
  onDestroyContainer,
}) => {
  const [filter, setFilter] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [copied, setCopied] = useState(false)
  const [shellOutput, setShellOutput] = useState('')
  const [shellCommand, setShellCommand] = useState('')
  const [shellStatus, setShellStatus] = useState<'closed' | 'connecting' | 'connected'>('closed')
  const [shellHistory, setShellHistory] = useState<string[]>([])
  const [historyIndex, setHistoryIndex] = useState(-1)
  const logContainerRef = useRef<HTMLDivElement>(null)
  const shellContainerRef = useRef<HTMLDivElement>(null)
  const shellInputRef = useRef<HTMLInputElement>(null)
  const shellSocketRef = useRef<WebSocket | null>(null)

  const filteredLogs = filter
    ? logs.filter((l) => l.toLowerCase().includes(filter.toLowerCase()))
    : logs

  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  useEffect(() => {
    setShellOutput('')
    setShellCommand('')
    setShellHistory([])
    setHistoryIndex(-1)
    if (!runId || !shellToken) {
      setShellStatus('closed')
      return
    }

    setShellStatus('connecting')
    setShellOutput('Starting per-run container console…\n')
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socketUrl = `${protocol}//${window.location.host}/api/runs/${encodeURIComponent(runId)}/shell`
    const socket = new WebSocket(socketUrl, ['dbt-shell', shellToken])
    shellSocketRef.current = socket
    socket.onopen = () => setShellStatus('connected')
    socket.onmessage = (event) => {
      setShellOutput((previous) => `${previous}${String(event.data)}`.slice(-100_000))
    }
    socket.onerror = () => setShellOutput((previous) => `${previous}\nProject shell connection failed.\n`)
    socket.onclose = () => setShellStatus('closed')

    return () => {
      shellSocketRef.current = null
      socket.close()
    }
  }, [runId, shellToken])

  useEffect(() => {
    if (shellContainerRef.current) {
      shellContainerRef.current.scrollTop = shellContainerRef.current.scrollHeight
    }
  }, [shellOutput])

  const submitShellCommand = (command: string) => {
    const trimmed = command.trim()
    const socket = shellSocketRef.current
    if (!trimmed || !socket || socket.readyState !== WebSocket.OPEN) return
    socket.send(`${command}\r`)
    setShellCommand('')
    setShellHistory((previous) => [...previous, trimmed].slice(-50))
    setHistoryIndex(-1)
    shellInputRef.current?.focus()
  }

  const displayedShellOutput = shellOutput
    .replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/\u001b\][^\u0007]*(?:\u0007|\u001b\\)/g, '')
    .replace(/\r\n?/g, '\n')
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '')

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
        className="flex-1 min-h-[180px] p-4 font-mono text-xs overflow-y-auto space-y-0.5 select-text"
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

      <div className="h-[230px] shrink-0 border-t border-[#30363d] bg-[#090c10] flex flex-col font-mono text-xs">
        <div className="px-3 py-2 border-b border-[#21262d] flex items-center justify-between gap-3">
          <span className="text-gray-300">Project console</span>
          <div className="flex items-center gap-3">
            {containerDestroyed ? (
              <span className="text-[10px] text-gray-400">Container destroyed · sandbox preserved</span>
            ) : runStatus && runStatus !== 'running' && shellToken && onDestroyContainer ? (
              <button
                type="button"
                onClick={onDestroyContainer}
                disabled={isDestroyingContainer}
                className="flex items-center gap-1 rounded border border-rose-500/40 px-2 py-1 text-[10px] text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
                title="Stop and remove this run's container. Saved results remain available."
              >
                <Trash2 className="h-3 w-3" />
                {isDestroyingContainer ? 'Destroying…' : 'Destroy container'}
              </button>
            ) : null}
            <span className="text-[10px] text-gray-500">Bash · isolated run container · no network</span>
          </div>
        </div>
        <div ref={shellContainerRef} className="flex-1 overflow-y-auto px-3 py-2 space-y-1 select-text">
          {!runId && <div className="text-gray-500">Run a project to open its console.</div>}
          {containerDestroyed && <div className="text-gray-400">This container has been destroyed. The sandbox files and run report are preserved.</div>}
          {runId && !containerDestroyed && !shellToken && <div className="text-gray-500">Shell access is unavailable for this run in this browser session.</div>}
          {runId && shellStatus === 'connecting' && <div className="text-amber-300">Connecting to the run container…</div>}
          <pre className="whitespace-pre-wrap break-words font-mono text-gray-200">{displayedShellOutput}</pre>
        </div>
        <form
          className="flex items-center gap-2 px-3 py-2 border-t border-[#21262d]"
          onSubmit={(event) => {
            event.preventDefault()
            submitShellCommand(shellCommand)
          }}
        >
          <span className="text-emerald-400 shrink-0">$</span>
          <input
            ref={shellInputRef}
            value={shellCommand}
            onChange={(event) => setShellCommand(event.target.value)}
            onKeyDown={(event) => {
              if (event.ctrlKey && event.key.toLowerCase() === 'c') {
                event.preventDefault()
                shellSocketRef.current?.send('\u0003')
                setShellCommand('')
                return
              }
              if (event.key === 'ArrowUp' && shellHistory.length) {
                event.preventDefault()
                const next = historyIndex < 0 ? shellHistory.length - 1 : Math.max(0, historyIndex - 1)
                setHistoryIndex(next)
                setShellCommand(shellHistory[next])
              } else if (event.key === 'ArrowDown' && historyIndex >= 0) {
                event.preventDefault()
                const next = historyIndex + 1
                setHistoryIndex(next >= shellHistory.length ? -1 : next)
                setShellCommand(next >= shellHistory.length ? '' : shellHistory[next])
              }
            }}
            disabled={!runId || !shellToken || shellStatus !== 'connected'}
            maxLength={1000}
            autoComplete="off"
            spellCheck={false}
            aria-label="Project console command"
            placeholder={!runId ? 'Run a project first' : shellToken ? 'Type a shell command' : 'Shell token unavailable'}
            className="min-w-0 flex-1 bg-transparent text-gray-100 outline-none placeholder:text-gray-600 disabled:cursor-not-allowed"
          />
          <button
            type="submit"
            disabled={!runId || !shellToken || shellStatus !== 'connected' || !shellCommand.trim()}
            className="rounded border border-[#30363d] px-2 py-1 text-gray-300 hover:text-white disabled:opacity-40"
          >
            {shellStatus === 'connected' ? 'Send' : 'Connecting…'}
          </button>
        </form>
      </div>
    </div>
  )
}
