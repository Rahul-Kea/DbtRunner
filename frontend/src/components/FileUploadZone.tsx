import React, { useRef, useState } from 'react'
import {
  FileArchive,
  Layers,
  CheckCircle2,
  X,
  Play,
  AlertCircle,
  FileSpreadsheet,
  Plus,
  Trash2,
  FileCode,
  GitBranch,
  Globe,
} from 'lucide-react'

interface FileUploadZoneProps {
  onStartRun: (formData: FormData) => void
  isLoading: boolean
}

export const FileUploadZone: React.FC<FileUploadZoneProps> = ({
  onStartRun,
  isLoading,
}) => {
  const [projectSource, setProjectSource] = useState<'zip' | 'git'>('zip')
  const [gitUrl, setGitUrl] = useState<string>('')
  const [gitBranch, setGitBranch] = useState<string>('')
  const [projectZip, setProjectZip] = useState<File | null>(null)
  const [rawDataFiles, setRawDataFiles] = useState<File[]>([])

  const [verifyRerun, setVerifyRerun] = useState<boolean>(true)
  const [compileOnly, setCompileOnly] = useState<boolean>(false)
  const [dragOverZone, setDragOverZone] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const projectInputRef = useRef<HTMLInputElement>(null)
  const rawDataInputRef = useRef<HTMLInputElement>(null)

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const getFileIcon = (filename: string) => {
    const ext = filename.split('.').pop()?.toLowerCase()
    if (ext === 'parquet') return <Layers className="w-4 h-4 text-blue-400 flex-shrink-0" />
    if (ext === 'json' || ext === 'ndjson') return <FileCode className="w-4 h-4 text-purple-400 flex-shrink-0" />
    if (ext === 'zip') return <FileArchive className="w-4 h-4 text-orange-400 flex-shrink-0" />
    return <FileSpreadsheet className="w-4 h-4 text-emerald-400 flex-shrink-0" />
  }

  const handleDrop = (
    e: React.DragEvent<HTMLDivElement>,
    zone: 'project' | 'raw_data'
  ) => {
    e.preventDefault()
    setDragOverZone(null)
    setErrorMessage(null)

    if (zone === 'raw_data') {
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        const supported = ['zip', 'csv', 'tsv', 'parquet', 'json', 'ndjson']
        const added: File[] = []
        for (let i = 0; i < e.dataTransfer.files.length; i++) {
          const f = e.dataTransfer.files[i]
          const ext = f.name.split('.').pop()?.toLowerCase() || ''
          if (supported.includes(ext)) {
            added.push(f)
          }
        }
        if (added.length === 0) {
          setErrorMessage('None of the dropped files are supported data files (.csv, .parquet, .json, .zip)')
          return
        }
        setRawDataFiles((prev) => {
          const existing = new Set(prev.map((f) => f.name))
          return [...prev, ...added.filter((f) => !existing.has(f.name))]
        })
      }
    } else if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0]
      const ext = file.name.split('.').pop()?.toLowerCase() || ''
      if (ext !== 'zip') {
        setErrorMessage('dbt project must be a .zip archive containing dbt_project.yml')
        return
      }
      setProjectZip(file)
    }
  }

  const handleRawFilesSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const supported = ['zip', 'csv', 'tsv', 'parquet', 'json', 'ndjson']
      const added: File[] = []
      for (let i = 0; i < e.target.files.length; i++) {
        const f = e.target.files[i]
        const ext = f.name.split('.').pop()?.toLowerCase() || ''
        if (supported.includes(ext)) {
          added.push(f)
        }
      }
      if (added.length === 0) {
        setErrorMessage('None of the selected files are supported data files (.csv, .parquet, .json, .zip)')
        return
      }
      setRawDataFiles((prev) => {
        const existing = new Set(prev.map((f) => f.name))
        return [...prev, ...added.filter((f) => !existing.has(f.name))]
      })
      setErrorMessage(null)
      e.target.value = ''
    }
  }

  const removeRawFile = (filename: string) => {
    setRawDataFiles((prev) => prev.filter((f) => f.name !== filename))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data = new FormData()
    data.append('threads', '1')
    data.append('verify_rerun', verifyRerun.toString())
    data.append('compile_only', compileOnly.toString())

    if (projectSource === 'zip') {
      if (!projectZip) {
        setErrorMessage('Please upload your dbt project (.zip).')
        return
      }
      data.append('project_zip', projectZip)
    } else {
      if (!gitUrl.trim()) {
        setErrorMessage('Please enter a Git repository URL.')
        return
      }
      data.append('git_url', gitUrl.trim())
      if (gitBranch.trim()) {
        data.append('git_branch', gitBranch.trim())
      }
    }

    if (rawDataFiles.length > 0) {
      rawDataFiles.forEach((file) => {
        data.append('raw_data_files', file)
      })
    }

    onStartRun(data)
  }

  return (
    <div className="max-w-4xl mx-auto py-6 px-4">
      {/* Title */}
      <div className="text-center mb-6">
        <h2 className="text-2xl font-bold text-white tracking-tight">
          Run dbt Project
        </h2>
        <p className="mt-1 text-sm text-gray-400 max-w-lg mx-auto">
          Upload a dbt project or provide a Git URL. Optionally add raw data files.
        </p>
      </div>

      {errorMessage && (
        <div className="mb-6 p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-start space-x-3 text-rose-300 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5 text-rose-400" />
          <span>{errorMessage}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* 1. dbt Project Source (Zip or Git) */}
          <div
            className={`relative rounded-2xl border p-5 transition-all flex flex-col justify-between min-h-[300px] ${
              projectSource === 'zip'
                ? projectZip
                  ? 'border-emerald-500/50 bg-emerald-950/10'
                  : dragOverZone === 'project'
                  ? 'border-orange-500 bg-orange-950/20'
                  : 'border-[#30363d] bg-[#161b22]'
                : gitUrl.trim()
                ? 'border-emerald-500/50 bg-emerald-950/10'
                : 'border-[#30363d] bg-[#161b22]'
            }`}
            onDragOver={(e) => {
              if (projectSource === 'zip') {
                e.preventDefault()
                setDragOverZone('project')
              }
            }}
            onDragLeave={() => setDragOverZone(null)}
            onDrop={(e) => {
              if (projectSource === 'zip') {
                handleDrop(e, 'project')
              }
            }}
          >
            {/* Header with Source Toggle Tabs */}
            <div className="flex items-center justify-between w-full mb-3">
              <span className="text-xs font-bold text-gray-300 uppercase tracking-wider">
                1. dbt Project
              </span>
              <div className="flex items-center p-0.5 rounded-lg bg-[#0d1117] border border-[#30363d]">
                <button
                  type="button"
                  onClick={() => setProjectSource('zip')}
                  className={`flex items-center space-x-1 px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                    projectSource === 'zip'
                      ? 'bg-orange-500 text-white'
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  <FileArchive className="w-3 h-3" />
                  <span>Upload .zip</span>
                </button>
                <button
                  type="button"
                  onClick={() => setProjectSource('git')}
                  className={`flex items-center space-x-1 px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                    projectSource === 'git'
                      ? 'bg-orange-500 text-white'
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  <GitBranch className="w-3 h-3" />
                  <span>Git URL</span>
                </button>
              </div>
            </div>

            {projectSource === 'zip' ? (
              /* Zip Upload Area */
              <div
                onClick={() => projectInputRef.current?.click()}
                className="flex-1 flex flex-col items-center justify-center cursor-pointer py-4 border border-dashed border-[#30363d] rounded-xl hover:border-gray-500 transition-colors"
              >
                <input
                  ref={projectInputRef}
                  type="file"
                  accept=".zip"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (file) {
                      const ext = file.name.split('.').pop()?.toLowerCase() || ''
                      if (ext !== 'zip') {
                        setErrorMessage('dbt project must be a .zip archive containing dbt_project.yml')
                        return
                      }
                      setProjectZip(file)
                      setErrorMessage(null)
                    }
                  }}
                />
                <div className="w-10 h-10 rounded-xl bg-orange-500/10 border border-orange-500/20 flex items-center justify-center text-orange-400 mb-2">
                  <FileArchive className="w-5 h-5" />
                </div>

                <span className="font-medium text-white text-xs">
                  Upload project archive (.zip)
                </span>
                <span className="text-[11px] text-gray-500 mt-0.5">
                  Contains dbt_project.yml, models, and tests
                </span>

                {projectZip ? (
                  <div
                    className="mt-3 px-3 py-1.5 rounded-lg bg-[#0d1117] border border-emerald-500/30 flex items-center space-x-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
                    <span className="text-xs text-emerald-300 font-mono font-medium truncate max-w-[180px]">
                      {projectZip.name}
                    </span>
                    <button
                      type="button"
                      onClick={() => setProjectZip(null)}
                      className="text-gray-400 hover:text-white p-0.5"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ) : (
                  <span className="mt-3 text-[11px] text-gray-500">
                    Click or drag file here
                  </span>
                )}
              </div>
            ) : (
              /* Git URL Input Area */
              <div className="flex-1 flex flex-col justify-between py-1 space-y-3">
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs font-semibold text-gray-300 mb-1 flex items-center space-x-1">
                      <Globe className="w-3 h-3 text-orange-400" />
                      <span>Git Repository URL</span>
                    </label>
                    <input
                      type="url"
                      value={gitUrl}
                      onChange={(e) => {
                        setGitUrl(e.target.value)
                        setErrorMessage(null)
                      }}
                      className="w-full px-3 py-2 rounded-xl bg-[#0d1117] border border-[#30363d] focus:border-orange-500 focus:outline-none text-xs text-white font-mono"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-gray-300 mb-1 flex items-center space-x-1">
                      <GitBranch className="w-3 h-3 text-orange-400" />
                      <span>Branch / Tag (Optional)</span>
                    </label>
                    <input
                      type="text"
                      value={gitBranch}
                      onChange={(e) => setGitBranch(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-[#0d1117] border border-[#30363d] focus:border-orange-500 focus:outline-none text-xs text-white font-mono"
                    />
                  </div>
                </div>

                <div className="text-[11px] text-gray-400 bg-[#0d1117]/60 border border-[#30363d]/60 rounded-lg p-2 leading-relaxed">
                  Supports repository URLs and subfolder links (/tree/main/subfolder).
                </div>
              </div>
            )}
          </div>

          {/* 2. Raw Data Files Area */}
          <div
            onDragOver={(e) => {
              e.preventDefault()
              setDragOverZone('raw_data')
            }}
            onDragLeave={() => setDragOverZone(null)}
            onDrop={(e) => handleDrop(e, 'raw_data')}
            onClick={() => rawDataInputRef.current?.click()}
            className={`relative rounded-2xl border p-5 transition-all flex flex-col justify-between min-h-[300px] cursor-pointer ${
              rawDataFiles.length > 0
                ? 'border-emerald-500/50 bg-emerald-950/10'
                : dragOverZone === 'raw_data'
                ? 'border-orange-500 bg-orange-950/20'
                : 'border-[#30363d] bg-[#161b22]'
            }`}
          >
            <input
              ref={rawDataInputRef}
              type="file"
              multiple
              accept=".zip,.csv,.tsv,.parquet,.json,.ndjson"
              className="hidden"
              onChange={handleRawFilesSelected}
            />

            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-bold text-gray-300 uppercase tracking-wider">
                  2. Raw Data (Optional)
                </span>
                {rawDataFiles.length > 0 && (
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                    {rawDataFiles.length} {rawDataFiles.length === 1 ? 'file' : 'files'}
                  </span>
                )}
              </div>

              <div className="flex flex-col items-center justify-center py-2 text-center">
                <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 mb-2">
                  <FileSpreadsheet className="w-5 h-5" />
                </div>
                <span className="text-xs font-medium text-white">
                  Add CSV, Parquet, or JSON files
                </span>
                <span className="text-[11px] text-gray-500 mt-0.5 max-w-xs">
                  Leave empty if your project contains seeds or when running a dry run
                </span>
              </div>
            </div>

            {rawDataFiles.length > 0 ? (
              <div
                className="mt-2 w-full space-y-1.5 max-h-32 overflow-y-auto pr-1"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="flex items-center justify-between text-[11px] text-gray-400 pb-1 border-b border-[#30363d]/50">
                  <span className="font-medium">Files to Load:</span>
                  <div className="flex items-center space-x-2">
                    <button
                      type="button"
                      onClick={() => rawDataInputRef.current?.click()}
                      className="text-orange-400 hover:text-orange-300 font-semibold flex items-center space-x-0.5 text-[11px]"
                    >
                      <Plus className="w-3 h-3" />
                      <span>Add</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setRawDataFiles([])}
                      className="text-gray-500 hover:text-rose-400 transition-colors"
                      title="Clear all"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>

                {rawDataFiles.map((f) => (
                  <div
                    key={f.name}
                    className="p-1.5 rounded-lg bg-[#0d1117] border border-[#30363d] flex items-center justify-between gap-2"
                  >
                    <div className="flex items-center space-x-2 truncate">
                      {getFileIcon(f.name)}
                      <div className="flex flex-col text-left truncate">
                        <span className="text-xs text-gray-200 truncate font-mono">
                          {f.name}
                        </span>
                        <span className="text-[10px] text-gray-400 font-mono">
                          {formatFileSize(f.size)}
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeRawFile(f.name)}
                      className="text-gray-500 hover:text-white p-1 flex-shrink-0"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center text-[11px] text-gray-500 py-2">
                Click or drag data files here
              </div>
            )}
          </div>
        </div>

        {/* Options & Action Bar */}
        <div className="p-4 rounded-2xl bg-[#161b22] border border-[#30363d] flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center space-x-5">
            <label className="flex items-center space-x-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={compileOnly}
                onChange={(e) => setCompileOnly(e.target.checked)}
                className="rounded border-[#30363d] text-orange-500 focus:ring-0 bg-[#0d1117] w-4 h-4"
              />
              <span className="text-xs text-gray-300 font-medium">
                Dry Run (Validate models without data)
              </span>
            </label>

            {!compileOnly && (
              <label className="flex items-center space-x-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={verifyRerun}
                  onChange={(e) => setVerifyRerun(e.target.checked)}
                  className="rounded border-[#30363d] text-orange-500 focus:ring-0 bg-[#0d1117] w-4 h-4"
                />
                <span className="text-xs text-gray-300 font-medium">
                  Check Idempotency (Rerun verification)
                </span>
              </label>
            )}
          </div>

          <button
            type="submit"
            disabled={
              isLoading ||
              (projectSource === 'zip' && !projectZip) ||
              (projectSource === 'git' && !gitUrl.trim())
            }
            className="flex items-center space-x-2 px-6 py-2.5 rounded-xl bg-orange-500 hover:bg-orange-600 text-white text-xs font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-md"
          >
            <Play className="w-4 h-4 fill-current" />
            <span>
              {isLoading
                ? 'Running...'
                : compileOnly
                ? 'Validate DAG'
                : 'Run dbt'}
            </span>
          </button>
        </div>
      </form>
    </div>
  )
}
