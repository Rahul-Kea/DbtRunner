import React, { useEffect, useRef, useState } from 'react'
import { Header } from './components/Header'
import { FileUploadZone } from './components/FileUploadZone'
import { RunStatusBar } from './components/RunStatusBar'
import { PipelineStepsView } from './components/PipelineStepsView'
import { ModelExecutionsTable } from './components/ModelExecutionsTable'
import { TerminalLogView } from './components/TerminalLogView'
import { RunHistorySidebar } from './components/RunHistorySidebar'
import { ContainerPanel } from './components/ContainerPanel'
import { IncrementalModelSelector } from './components/IncrementalModelSelector'
import type { PipelineRemediation, RunReport, RunSummary } from './types'

export const App: React.FC = () => {
  const [runsList, setRunsList] = useState<RunSummary[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [activeSessionToken, setActiveSessionToken] = useState<string | undefined>()
  const [activeShellToken, setActiveShellToken] = useState<string | undefined>()
  const [activeReport, setActiveReport] = useState<RunReport | null>(null)
  const [activeLogs, setActiveLogs] = useState<string[]>([])
  const [isStreaming, setIsStreaming] = useState<boolean>(false)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [isDestroyingContainer, setIsDestroyingContainer] = useState<boolean>(false)
  const [showHistory, setShowHistory] = useState<boolean>(false)
  const [showContainers, setShowContainers] = useState<boolean>(false)
  const [showIncrementalSelector, setShowIncrementalSelector] = useState<boolean>(false)
  const [activeTab, setActiveTab] = useState<'models' | 'steps' | 'terminal'>('terminal')

  const eventSourceRef = useRef<EventSource | null>(null)
  const activeSessionRef = useRef<{ id: string | null; token?: string }>({ id: null })

  useEffect(() => {
    activeSessionRef.current = { id: activeSessionId, token: activeSessionToken }
  }, [activeSessionId, activeSessionToken])

  const rememberShellToken = (runId: string, token?: string) => {
    setActiveShellToken(token)
    if (!token) return
    try {
      sessionStorage.setItem(`dbt-runner-shell:${runId}`, token)
    } catch {
      // The console remains unavailable if browser session storage is disabled.
    }
  }

  const rememberProjectSession = (sessionId?: string | null, token?: string) => {
    setActiveSessionId(sessionId || null)
    setActiveSessionToken(token)
    if (!sessionId || !token) return
    try {
      sessionStorage.setItem(`dbt-runner-session:${sessionId}`, token)
    } catch {
      // Server-side idle expiry still removes the container if storage is unavailable.
    }
  }

  const leaveProjectSession = (sessionId?: string | null, token?: string) => {
    if (!sessionId || !token) return
    const url = `/api/sessions/${encodeURIComponent(sessionId)}/leave`
    const body = new Blob([JSON.stringify({ session_token: token })], { type: 'application/json' })
    if (!navigator.sendBeacon(url, body)) {
      void fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_token: token }), keepalive: true })
    }
    try {
      sessionStorage.removeItem(`dbt-runner-session:${sessionId}`)
    } catch {
      // The server-side idle timeout is the fallback.
    }
  }

  useEffect(() => {
    const handlePageHide = () => {
      const session = activeSessionRef.current
      leaveProjectSession(session.id, session.token)
    }
    window.addEventListener('pagehide', handlePageHide)
    return () => window.removeEventListener('pagehide', handlePageHide)
  }, [])

  useEffect(() => {
    if (!activeSessionId || !activeSessionToken) return
    const heartbeat = async () => {
      try {
        await fetch(`/api/sessions/${encodeURIComponent(activeSessionId)}/heartbeat`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_token: activeSessionToken }),
        })
      } catch {
        // The server expires inactive sessions even if the browser loses connectivity.
      }
    }
    void heartbeat()
    const timer = setInterval(heartbeat, 20_000)
    return () => clearInterval(timer)
  }, [activeSessionId, activeSessionToken])

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
        } else if (data.type === 'stage_log') {
          setActiveLogs((prev) => [...prev, `[${data.stage} ${data.stream}] ${data.line}`])
        } else if (data.type === 'stage') {
          setActiveReport((current) => {
            const stages = current?.pipeline_stages || []
            const nextStage = { stage_id: data.stage_id, status: data.status, summary: data.summary, details: data.details || {} }
            const found = stages.some((stage) => stage.stage_id === data.stage_id)
            return {
              ...(current || { run_id: runId, overall_status: 'running', steps: [], model_executions: [], model_test_results: [], failure_details: [], warning_details: [] } as unknown as RunReport),
              pipeline_stages: found ? stages.map((stage) => stage.stage_id === data.stage_id ? { ...stage, ...nextStage } : stage) : [...stages, nextStage],
            }
          })
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

  const loadRunReport = async (runId: string): Promise<RunReport | null> => {
    try {
      const res = await fetch(`/api/runs/${runId}`)
      if (res.ok) {
        const data: RunReport = await res.json()
        setActiveReport(data)
        if (data.session_id) {
          setActiveSessionId(data.session_id)
          try {
            setActiveSessionToken(sessionStorage.getItem(`dbt-runner-session:${data.session_id}`) || undefined)
          } catch {
            setActiveSessionToken(undefined)
          }
        }
        return data
      }
    } catch (err) {
      console.error('Failed to fetch run report', err)
    }
    return null
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
  const handleCompile = async (formData: FormData) => {
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
      rememberProjectSession(data.session_id, data.session_token)
      setActiveTab('terminal')
      startStream(data.run_id)
      fetchRuns()
    } catch (err: any) {
      alert(`Error starting dbt compile: ${err.message}`)
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
      const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Pipeline run execution failed')
      }

      const data = await res.json()
      setShowIncrementalSelector(false)
      setActiveRunId(data.run_id)
      rememberShellToken(data.run_id, data.shell_token)
      rememberProjectSession(data.session_id, data.session_token)
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

  const handleResumePipeline = async (remediation: PipelineRemediation) => {
    if (!activeRunId) return
    setIsLoading(true)
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(activeRunId)}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(remediation),
      })
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Pipeline could not resume')
      }
      const data = await res.json()
      setActiveRunId(data.run_id)
      rememberShellToken(data.run_id, data.shell_token)
      rememberProjectSession(data.session_id, data.session_token)
      setActiveLogs([])
      setActiveReport(null)
      setActiveTab('steps')
      startStream(data.run_id)
      fetchRuns()
    } catch (err: any) {
      alert(`Could not resume source preparation: ${err.message}`)
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
      const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/full-refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ execution_mode: 'run' }),
      })

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Full refresh could not be started')
      }

      const data = await res.json()
      setShowIncrementalSelector(false)
      setActiveRunId(data.run_id)
      rememberShellToken(data.run_id, data.shell_token)
      rememberProjectSession(data.session_id, data.session_token)
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

  const handleTriggerIncrementalFullRefresh = async (
    selectedModels: string[],
    allIncremental: boolean
  ) => {
    if (!activeRunId) return
    setIsLoading(true)
    try {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
        setIsStreaming(false)
      }
      const res = await fetch(`/api/runs/${encodeURIComponent(activeRunId)}/full-refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          execution_mode: 'run',
          models: selectedModels,
          all_incremental: allIncremental,
        }),
      })

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Selective full refresh could not be started')
      }

      const data = await res.json()
      setShowIncrementalSelector(false)
      setActiveRunId(data.run_id)
      rememberShellToken(data.run_id, data.shell_token)
      rememberProjectSession(data.session_id, data.session_token)
      setActiveLogs([])
      setActiveReport(null)
      setActiveTab('terminal')
      startStream(data.run_id)
      fetchRuns()
    } catch (err: any) {
      alert(`Error starting selective full refresh: ${err.message}`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleSelectRun = async (runId: string) => {
    const previousSession = activeSessionRef.current
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
      setIsStreaming(false)
    }

    setShowIncrementalSelector(false)
    setActiveRunId(runId)
    try {
      setActiveShellToken(sessionStorage.getItem(`dbt-runner-shell:${runId}`) || undefined)
    } catch {
      setActiveShellToken(undefined)
    }
    setActiveLogs([])
    setIsLoading(true)

    const [selectedReport] = await Promise.all([loadRunReport(runId), loadRunLogs(runId)])
    if (previousSession.id && selectedReport?.session_id !== previousSession.id) {
      leaveProjectSession(previousSession.id, previousSession.token)
    }
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
        const errorData = await res.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Could not destroy the run container')
      }
      setActiveReport((current) => current ? { ...current, container_destroyed: true } : current)
      setActiveLogs((current) => [...current, 'Run container destroyed; sandbox files and reports were preserved.'])
      setActiveShellToken(undefined)
      leaveProjectSession(activeSessionId, activeSessionToken)
      setActiveSessionId(null)
      setActiveSessionToken(undefined)
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
    leaveProjectSession(activeSessionId, activeSessionToken)
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
      setIsStreaming(false)
    }
    setShowIncrementalSelector(false)
    setActiveRunId(null)
    setActiveSessionId(null)
    setActiveSessionToken(undefined)
    setActiveShellToken(undefined)
    setActiveReport(null)
    setActiveLogs([])
    setActiveTab('terminal')
  }

  const handlePanelContainerDestroyed = (runId: string) => {
    if (activeRunId === runId) {
      setActiveReport((current) => current ? { ...current, container_destroyed: true } : current)
      setActiveShellToken(undefined)
      if (activeSessionId) {
        try {
          sessionStorage.removeItem(`dbt-runner-session:${activeSessionId}`)
        } catch {
          // Container removal is complete even if browser storage is unavailable.
        }
        setActiveSessionId(null)
        setActiveSessionToken(undefined)
      }
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
        onNewProject={handleNewRun}
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
            onCompile={handleCompile}
            isLoading={isLoading}
          />
        ) : (
          <div className="space-y-6">
            <RunStatusBar
              report={
                activeReport || {
                  run_id: activeRunId,
                  overall_status: 'running',
                  database_type: 'unknown',
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
              onSelectTab={(tab) => {
                setShowIncrementalSelector(false)
                setActiveTab(tab)
              }}
              isStreaming={isStreaming}
              onTriggerRun={handleTriggerRun}
              onTriggerFullRefresh={handleTriggerFullRefresh}
              onOpenIncrementalSelector={() => setShowIncrementalSelector(true)}
              isTriggeringAction={isLoading}
            />

            {/* Incremental Model Selector View or Standard Tab Views */}
            {showIncrementalSelector ? (
              <IncrementalModelSelector
                runId={activeRunId}
                onCancel={() => setShowIncrementalSelector(false)}
                onRunFullRefresh={handleTriggerIncrementalFullRefresh}
                isLoading={isLoading}
              />
            ) : (
              <>
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
                  <PipelineStepsView
                    stages={activeReport?.pipeline_stages || []}
                    steps={activeReport?.steps || []}
                    diagnostics={activeReport?.diagnostics || []}
                    artifactSnapshots={activeReport?.artifact_snapshots || {}}
                    onResume={handleResumePipeline}
                    isResuming={isLoading}
                  />
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
              </>
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
