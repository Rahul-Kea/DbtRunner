import React, { useEffect, useRef, useState } from 'react'
import { Header } from './components/Header'
import { FileUploadZone } from './components/FileUploadZone'
import { RunStatusBar } from './components/RunStatusBar'
import { PipelineStepsView } from './components/PipelineStepsView'
import { ModelExecutionsTable } from './components/ModelExecutionsTable'
import { TerminalLogView } from './components/TerminalLogView'
import { RunHistorySidebar } from './components/RunHistorySidebar'
import type { RunReport, RunSummary } from './types'

export const App: React.FC = () => {
  const [runsList, setRunsList] = useState<RunSummary[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [activeReport, setActiveReport] = useState<RunReport | null>(null)
  const [activeLogs, setActiveLogs] = useState<string[]>([])
  const [isStreaming, setIsStreaming] = useState<boolean>(false)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [showHistory, setShowHistory] = useState<boolean>(false)
  const [activeTab, setActiveTab] = useState<'models' | 'steps' | 'terminal'>('terminal')

  const eventSourceRef = useRef<EventSource | null>(null)

  const fetchRuns = async () => {
    try {
      const res = await fetch('/api/runs')
      if (res.ok) {
        const data = await res.json()
        setRunsList(data)
      }
    } catch (err) {
      console.error('Error fetching runs:', err)
    }
  }

  useEffect(() => {
    fetchRuns()
    const interval = setInterval(() => {
      fetchRuns()
    }, 5000)
    return () => clearInterval(interval)
  }, [])

  // 2. Stream logs via SSE
  const startStream = (runId: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    setIsStreaming(true)
    const es = new EventSource(`/api/runs/${runId}/stream`)
    eventSourceRef.current = es

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'log') {
          setActiveLogs((prev) => [...prev, data.line])
        } else if (data.type === 'complete') {
          setIsStreaming(false)
          es.close()
          eventSourceRef.current = null
          // Fetch full final report
          loadRunReport(runId)
          fetchRuns()
        }
      } catch (err) {
        console.error('Failed to parse SSE payload', err)
      }
    }

    es.onerror = () => {
      // In case of error/connection drop, poll the final report
      setIsStreaming(false)
      es.close()
      eventSourceRef.current = null
      loadRunReport(runId)
      fetchRuns()
    }
  }

  const loadRunReport = async (runId: string) => {
    try {
      const res = await fetch(`/api/runs/${runId}`)
      if (res.ok) {
        const data: RunReport = await res.json()
        setActiveReport(data)
      }
    } catch (err) {
      console.error('Failed to fetch run report', err)
    }
  }

  const loadRunLogs = async (runId: string) => {
    try {
      const res = await fetch(`/api/runs/${runId}/logs`)
      if (res.ok) {
        const data = await res.json()
        if (data.logs) {
          setActiveLogs(data.logs.split('\n'))
        }
      }
    } catch (err) {
      console.error('Failed to fetch run logs', err)
    }
  }

  // 3. User Actions
  const handleStartRun = async (formData: FormData) => {
    setIsLoading(true)
    setActiveLogs([])
    setActiveReport(null)

    try {
      const res = await fetch('/api/run', {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.detail || 'Run execution failed to initiate')
      }

      const data = await res.json()
      setActiveRunId(data.run_id)
      setActiveTab('terminal')
      startStream(data.run_id)
      fetchRuns()
    } catch (err: any) {
      alert(`Error starting dbt run: ${err.message}`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleSelectRun = async (runId: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
      setIsStreaming(false)
    }

    setActiveRunId(runId)
    setActiveLogs([])
    setIsLoading(true)

    await Promise.all([loadRunReport(runId), loadRunLogs(runId)])
    setActiveTab('models')
    setIsLoading(false)
  }

  const handleNewRun = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
      setIsStreaming(false)
    }
    setActiveRunId(null)
    setActiveReport(null)
    setActiveLogs([])
    setActiveTab('terminal')
  }

  return (
    <div className="min-h-screen bg-[#0d1117] text-white flex flex-col">
      <Header
        onNewRun={handleNewRun}
        onToggleHistory={() => setShowHistory((prev) => !prev)}
        showHistory={showHistory}
        activeRunId={activeRunId}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6">
        {!activeRunId ? (
          <FileUploadZone
            onStartRun={handleStartRun}
            isLoading={isLoading}
          />
        ) : (
          <div className="space-y-6">
            <RunStatusBar
              report={
                activeReport || {
                  run_id: activeRunId,
                  overall_status: 'running',
                  database_type: 'ducklake',
                  project_dir: 'Isolated Sandbox',
                  started_at: '',
                  finished_at: '',
                  data_location: '',
                  ducklake_metadata_location: '',
                  steps: [],
                  model_test_results: [],
                  model_executions: [],
                  log_file: '',
                  structured_log_file: '',
                  report_file: '',
                  config_file: '',
                  rerun_policy: '',
                  sandbox_cleanup_status: 'pending',
                  object_validation: { status: 'running' },
                  dag_validation: { status: 'running' },
                  rerun_verification: { status: 'running' },
                  failure_details: [],
                  warning_details: [],
                }
              }
              activeTab={activeTab}
              onSelectTab={setActiveTab}
              isStreaming={isStreaming}
            />

            {/* Tab Views (Condensed to 3 views) */}
            {activeTab === 'models' && (
              <ModelExecutionsTable
                executions={activeReport?.model_executions || []}
                runId={activeRunId}
                objectValidation={activeReport?.object_validation}
                failures={activeReport?.failure_details || []}
                warnings={activeReport?.warning_details || []}
              />
            )}

            {activeTab === 'steps' && (
              <PipelineStepsView steps={activeReport?.steps || []} />
            )}

            {activeTab === 'terminal' && (
              <TerminalLogView
                logs={activeLogs}
                isStreaming={isStreaming}
                runId={activeRunId}
              />
            )}
          </div>
        )}
      </main>

      {/* Execution History Drawer */}
      <RunHistorySidebar
        isOpen={showHistory}
        onClose={() => setShowHistory(false)}
        runs={runsList}
        activeRunId={activeRunId}
        onSelectRun={handleSelectRun}
        onRefresh={fetchRuns}
        isLoading={isLoading}
      />
    </div>
  )
}

export default App
