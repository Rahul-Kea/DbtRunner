import React, { useCallback, useEffect, useState } from 'react'
import { Container, RefreshCw, Trash2, X } from 'lucide-react'

interface AppContainer {
  container_id: string
  name: string
  image: string
  status: string
  created: string
  run_id: string
  session_id: string
}

interface ContainerPanelProps {
  isOpen: boolean
  onClose: () => void
  onContainerDestroyed: (runId: string) => void
}

export const ContainerPanel: React.FC<ContainerPanelProps> = ({
  isOpen,
  onClose,
  onContainerDestroyed,
}) => {
  const [containers, setContainers] = useState<AppContainer[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [removingId, setRemovingId] = useState<string | null>(null)
  const [error, setError] = useState('')

  const refreshContainers = useCallback(async () => {
    setIsLoading(true)
    setError('')
    try {
      const response = await fetch('/api/containers')
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not load containers')
      setContainers(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load containers')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isOpen) void refreshContainers()
  }, [isOpen, refreshContainers])

  const destroyContainer = async (container: AppContainer) => {
    let sessionToken: string | null = null
    try {
      sessionToken = sessionStorage.getItem(`dbt-runner-session:${container.session_id}`)
    } catch {
      // Without the run token, the API will reject the destructive request.
    }
    if (!sessionToken) {
      setError(`No active project session token is available for ${container.session_id}.`)
      return
    }
    setRemovingId(container.container_id)
    setError('')
    try {
      const response = await fetch(`/api/containers/${encodeURIComponent(container.container_id)}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_token: sessionToken }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not destroy container')
      setContainers((current) => current.filter((item) => item.container_id !== container.container_id))
      onContainerDestroyed(container.run_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not destroy container')
    } finally {
      setRemovingId(null)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex w-80 flex-col border-l border-[#30363d] bg-[#161b22] shadow-2xl sm:w-[28rem]">
      <div className="flex items-center justify-between border-b border-[#30363d] p-4">
        <div className="flex items-center gap-2">
          <Container className="h-4 w-4 text-orange-400" />
          <h2 className="text-sm font-bold text-white">Application containers</h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void refreshContainers()}
            disabled={isLoading}
            className="rounded p-1 text-gray-400 hover:bg-[#21262d] hover:text-white disabled:opacity-50"
            title="Refresh containers"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-[#21262d] hover:text-white"
            title="Close containers panel"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="border-b border-[#30363d] px-4 py-3 text-xs text-gray-400">
        Containers created by dbt Runner. Removing one preserves its saved report and sandbox files.
      </div>

      {error && <div className="mx-4 mt-4 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">{error}</div>}

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {isLoading && containers.length === 0 ? (
          <div className="py-12 text-center text-xs text-gray-500">Loading containers…</div>
        ) : containers.length === 0 ? (
          <div className="py-12 text-center text-xs text-gray-500">No dbt Runner containers found.</div>
        ) : containers.map((container) => {
          const isRunning = container.status.toLowerCase().startsWith('up')
          const isRemoving = removingId === container.container_id
          let canDestroy = false
          try {
            canDestroy = Boolean(sessionStorage.getItem(`dbt-runner-shell:${container.run_id}`))
          } catch {
            canDestroy = false
          }
          return (
            <div key={container.container_id} className="rounded-xl border border-[#30363d] bg-[#0d1117] p-3.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate font-mono text-xs font-semibold text-white">{container.name}</div>
                  <div className="mt-1 truncate text-[11px] text-gray-500">{container.image}</div>
                </div>
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${isRunning ? 'bg-emerald-500/15 text-emerald-300' : 'bg-gray-500/15 text-gray-300'}`}>
                  {isRunning ? 'Running' : 'Stopped'}
                </span>
              </div>
              <div className="mt-3 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-[11px] text-gray-400">
                <span>Run</span><span className="truncate font-mono text-gray-300">{container.run_id || 'unknown'}</span>
                <span>Created</span><span className="truncate">{container.created}</span>
                <span>Status</span><span className="truncate">{container.status}</span>
                <span>ID</span><span className="truncate font-mono">{container.container_id}</span>
              </div>
              <button
                type="button"
                onClick={() => void destroyContainer(container)}
                disabled={isRemoving || !canDestroy}
                className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg border border-rose-500/35 px-3 py-2 text-xs font-medium text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
                title={!canDestroy ? 'Run access token unavailable in this browser session' : isRunning ? 'Stop and remove this running container' : 'Remove this stopped container'}
              >
                <Trash2 className="h-3.5 w-3.5" />
                {isRemoving ? 'Destroying…' : isRunning ? 'Stop and destroy' : 'Destroy'}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
