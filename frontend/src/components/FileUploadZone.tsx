import React, { useRef, useState } from 'react'
import {
  FileArchive,
  CheckCircle2,
  X,
  AlertCircle,
  FileCode,
  GitBranch,
  Globe,
  Search,
} from 'lucide-react'

interface FileUploadZoneProps {
  onCompile: (formData: FormData) => void
  isLoading: boolean
}

export const FileUploadZone: React.FC<FileUploadZoneProps> = ({
  onCompile,
  isLoading,
}) => {
  const [projectSource, setProjectSource] = useState<'zip' | 'git'>('zip')
  const [gitUrl, setGitUrl] = useState<string>('')
  const [gitBranch, setGitBranch] = useState<string>('')
  const [projectZip, setProjectZip] = useState<File | null>(null)

  const [modelSelect, setModelSelect] = useState<string>('')
  const [runTests, setRunTests] = useState<boolean>(true)
  const [dragOverZone, setDragOverZone] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const projectInputRef = useRef<HTMLInputElement>(null)
  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOverZone(null)
    setErrorMessage(null)

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0]
      const ext = file.name.split('.').pop()?.toLowerCase() || ''
      if (ext !== 'zip') {
        setErrorMessage('dbt project must be a .zip archive containing dbt_project.yml')
        return
      }
      setProjectZip(file)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data = new FormData()
    data.append('verify_rerun', 'false')
    data.append('compile_only', 'true')
    data.append('execution_mode', 'compile')
    data.append('full_refresh', 'false')
    data.append('run_tests', String(runTests))
    if (modelSelect.trim()) {
      data.append('select', modelSelect.trim())
    }
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

    onCompile(data)
  }

  return (
    <div className="max-w-4xl mx-auto py-6 px-4">
      {/* Title */}
      <div className="text-center mb-6">
        <h2 className="text-2xl font-bold text-white tracking-tight">
          Compile dbt Project
        </h2>
        <p className="mt-1 text-sm text-gray-400 max-w-lg mx-auto">
          Upload a dbt project or provide a Git URL, then compile it in an isolated sandbox.
        </p>
      </div>

      {errorMessage && (
        <div className="mb-6 p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-start space-x-3 text-rose-300 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5 text-rose-400" />
          <span>{errorMessage}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="grid grid-cols-1 gap-6">
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
            onDrop={(e) => projectSource === 'zip' && handleDrop(e)}
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

        </div>

        {/* 2. Compile Scope */}
        <div className="p-5 rounded-2xl bg-[#161b22] border border-[#30363d] space-y-4">
          <div className="flex items-center justify-between border-b border-[#30363d]/60 pb-3">
            <span className="text-xs font-bold text-gray-300 uppercase tracking-wider">
              2. Compile Scope
            </span>
          </div>

          <div className="flex items-center gap-3 rounded-xl border border-[#30363d] bg-[#0d1117] p-3.5">
            <FileCode className="h-4 w-4 shrink-0 text-blue-400" />
            <div>
              <div className="text-xs font-bold text-gray-200">dbt compile · Dry run</div>
              <div className="mt-1 text-[11px] text-gray-400">
                Compile SQL and validate the DAG and references. Run dbt commands from the project console when needed.
              </div>
            </div>
          </div>

          {/* Model Selection Input */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-gray-300">
                Model Selection <span className="font-mono text-gray-500 font-normal">(--select / -s)</span>
              </label>
              <span className="text-[10px] text-gray-500">Optional: leave empty to compile the entire project</span>
            </div>
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-2.5 text-gray-500" />
              <input
                type="text"
                value={modelSelect}
                onChange={(e) => setModelSelect(e.target.value)}
                placeholder="e.g. model_a model_b model_c or +my_model or tag:daily"
                className="w-full bg-[#0d1117] border border-[#30363d] rounded-xl pl-9 pr-3 py-2 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-orange-500 font-mono"
              />
            </div>
            {/* Quick Syntax Hints */}
            <div className="flex flex-wrap items-center gap-1.5 pt-0.5 text-[11px] text-gray-400">
              <span className="text-gray-500 font-medium">Examples:</span>
              <span className="inline-flex items-center space-x-1 font-mono bg-[#0d1117] px-1.5 py-0.5 rounded border border-[#30363d] text-gray-300">
                <span>m1 m2 m3</span>
                <span className="text-gray-500 font-sans text-[10px]">(multiple models)</span>
              </span>
              <span className="inline-flex items-center space-x-1 font-mono bg-[#0d1117] px-1.5 py-0.5 rounded border border-[#30363d] text-gray-300">
                <span>+model</span>
                <span className="text-gray-500 font-sans text-[10px]">(+ upstream)</span>
              </span>
              <span className="inline-flex items-center space-x-1 font-mono bg-[#0d1117] px-1.5 py-0.5 rounded border border-[#30363d] text-gray-300">
                <span>model+</span>
                <span className="text-gray-500 font-sans text-[10px]">(+ downstream)</span>
              </span>
              <span className="inline-flex items-center space-x-1 font-mono bg-[#0d1117] px-1.5 py-0.5 rounded border border-[#30363d] text-gray-300">
                <span>path:models/marts</span>
              </span>
              <span className="inline-flex items-center space-x-1 font-mono bg-[#0d1117] px-1.5 py-0.5 rounded border border-[#30363d] text-gray-300">
                <span>tag:daily</span>
              </span>
            </div>
          </div>

        </div>

        {/* Submit Action Bar */}
        <div className="flex items-center justify-between pt-2">
          <label className="flex items-center gap-2 text-xs text-gray-300">
            <input type="checkbox" checked={runTests} onChange={(event) => setRunTests(event.target.checked)} />
            Run dbt tests after model execution
          </label>
          <button
            type="submit"
            disabled={
              isLoading ||
              (projectSource === 'zip' && !projectZip) ||
              (projectSource === 'git' && !gitUrl.trim())
            }
            className="flex items-center space-x-2 px-8 py-3 rounded-xl bg-orange-500 hover:bg-orange-600 text-white text-xs font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-md hover:shadow-orange-500/20"
          >
            <FileCode className="w-4 h-4" />
            <span>{isLoading ? 'Compiling…' : 'Compile Models'}</span>
          </button>
        </div>
      </form>
    </div>
  )
}
