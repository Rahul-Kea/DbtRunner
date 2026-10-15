import React, { useEffect, useRef, useState } from 'react'
import { Header } from './components/Header'
import { FileUploadZone } from './components/FileUploadZone'
import { RunStatusBar } from './components/RunStatusBar'
import { PipelineStepsView } from './components/PipelineStepsView'
import { ModelExecutionsTable } from './components/ModelExecutionsTable'
import { TerminalLogView } from './components/TerminalLogView'
import { RunHistorySidebar } from './components/RunHistorySidebar'
import { ContainerPanel } from './components/ContainerPanel'
import type { RunReport, RunSummary } from './types'

export const App: React.FC = () => {
  const [runsList, setRunsList] = useState<RunSummary[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [activeShellToken, setActiveShellToken] = useState<string | undefined>()
  const [activeReport, setActiveReport] = useState<RunReport | null>(null)
  const [activeLogs, setActiveLogs] = useState<string[]>([])
  const [isStreaming, setIsStreaming] = useState<boolean>(false)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [isDestroyingContainer, setIsDestroyingContainer] = useState<boolean>(false)
  const [showHistory, setShowHistory] = useState<boolean>(false)
  const [showContainers, setShowContainers] = useState<boolean>(false)
  const [activeTab, setActiveTab] = useState<'models' | 'steps' | 'terminal'>('terminal')

  const eventSourceRef = useRef<EventSource | null>(null)

  const rememberShellToken = (runId: string, token?: string) => {
    setActiveShellToken(token)
    if (!token) return
    try {
      sessionStorage.setItem(`dbt-runner-shell:${runId}`, token)
    } catch {
      // The console remains unavailable if browser session storage is disabled.
    }
  }

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
      rememberShellToken(data.run_id, data.shell_token)
      setActiveTab('terminal')
      startStream(data.run_id)
      fetchRuns()
    } catch (err: any) {
      alert(`Error starting dbt run: ${err.message}`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleTriggerRun = async (runId: string) => {
    setIsLoading(true)
    try {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
        setIsStreaming(false)
      }
      const res = await fetch(`/api/runs/${runId}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })

      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.detail || 'Pipeline run execution failed')
      }

      const data = await res.json()
      setActiveRunId(data.run_id)
      rememberShellToken(data.run_id, data.shell_token)
      setActiveLogs([])
      setActiveReport(null)
      setActiveTab('terminal')
      startStream(data.run_id)
      fetchRuns()
    } catch (err: any) {
      alert(`Error starting pipeline run: ${err.message}`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleTriggerFullRefresh = async (runId: string) => {
    setIsLoading(true)
    try {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
        setIsStreaming(false)
      }
      const res = await fetch(`/api/runs/${runId}/full-refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          execution_mode: activeReport?.execution_mode || undefined,
        }),
      })

      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.detail || 'Full refresh run execution failed')
      }

      const data = await res.json()
      setActiveRunId(data.run_id)
      rememberShellToken(data.run_id, data.shell_token)
      setActiveLogs([])
      setActiveReport(null)
      setActiveTab('terminal')
      startStream(data.run_id)
      fetchRuns()
    } catch (err: any) {
      alert(`Error starting full refresh: ${err.message}`)
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
    try {
      setActiveShellToken(sessionStorage.getItem(`dbt-runner-shell:${runId}`) || undefined)
    } catch {
      setActiveShellToken(undefined)
    }
    setActiveLogs([])
    setIsLoading(true)

    await Promise.all([loadRunReport(runId), loadRunLogs(runId)])
    setActiveTab('models')
    setIsLoading(false)
  }

  const handleDestroyContainer = async () => {
    if (!activeRunId || !activeShellToken) return
    setIsDestroyingContainer(true)
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(activeRunId)}/destroy-container`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shell_token: activeShellToken }),
      })
      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.detail || 'Could not destroy the run container')
      }
      setActiveReport((current) => current ? { ...current, container_destroyed: true } : current)
      setActiveLogs((current) => [...current, 'Run container destroyed; sandbox files and reports were preserved.'])
      setActiveShellToken(undefined)
      try {
        sessionStorage.removeItem(`dbt-runner-shell:${activeRunId}`)
      } catch {
        // The server has already invalidated container access.
      }
      fetchRuns()
    } catch (err: any) {
      alert(`Error destroying run container: ${err.message}`)
    } finally {
      setIsDestroyingContainer(false)
    }
  }

  const handleNewRun = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
      setIsStreaming(false)
    }
    setActiveRunId(null)
    setActiveShellToken(undefined)
    setActiveReport(null)
    setActiveLogs([])
    setActiveTab('terminal')
  }

  const handlePanelContainerDestroyed = (runId: string) => {
    if (activeRunId === runId) {
      setActiveReport((current) => current ? { ...current, container_destroyed: true } : current)
      setActiveShellToken(undefined)
      try {
        sessionStorage.removeItem(`dbt-runner-shell:${runId}`)
      } catch {
        // Container removal is complete even if browser storage is unavailable.
      }
    }
    fetchRuns()
  }

  return (
    <div className="min-h-screen bg-[#0d1117] text-white flex flex-col">
      <Header
        onNewRun={handleNewRun}
        onToggleHistory={() => {
          setShowHistory((prev) => !prev)
          setShowContainers(false)
        }}
        showHistory={showHistory}
        onToggleContainers={() => {
          setShowContainers((prev) => !prev)
          setShowHistory(false)
        }}
        showContainers={showContainers}
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
              onTriggerRun={handleTriggerRun}
              onTriggerFullRefresh={handleTriggerFullRefresh}
              isTriggeringAction={isLoading}
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
                shellToken={activeShellToken}
                runStatus={activeReport?.overall_status || 'running'}
                containerDestroyed={activeReport?.container_destroyed || false}
                isDestroyingContainer={isDestroyingContainer}
                onDestroyContainer={handleDestroyContainer}
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
      <ContainerPanel
        isOpen={showContainers}
        onClose={() => setShowContainers(false)}
        onContainerDestroyed={handlePanelContainerDestroyed}
      />
    </div>
  )
}

export default App
