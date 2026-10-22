import React, { useMemo, useState } from 'react'
import { CheckCircle2, XCircle, Clock, Terminal, ChevronDown, ChevronRight, CircleAlert } from 'lucide-react'
import type { PipelineRemediation, PipelineStage, StepResult } from '../types'

interface PipelineStepsViewProps {
  stages?: PipelineStage[]
  steps: StepResult[]
  diagnostics?: Array<{ category: string; message: string; stage_id: string; next_action: string }>
  artifactSnapshots?: Record<string, any>
  onResume?: (remediation: PipelineRemediation) => void
  isResuming?: boolean
}

const stageNames: Record<string, string> = {
  project_detected: '1. Project detected',
  environment_ready: '2. Environment ready',
  source_data_ready: '3. Source data ready',
  compilation_passed: '4. Compilation passed',
  models_executed: '5. Models executed',
}

const statusClass: Record<string, string> = {
  passed: 'bg-emerald-500/20 text-emerald-300',
  failed: 'bg-rose-500/20 text-rose-300',
  running: 'bg-amber-500/20 text-amber-300',
  skipped: 'bg-slate-700 text-slate-300',
  needs_configuration: 'bg-orange-500/20 text-orange-200',
  pending: 'bg-gray-800 text-gray-400',
}

export const PipelineStepsView: React.FC<PipelineStepsViewProps> = ({ stages = [], steps, diagnostics = [], artifactSnapshots = {}, onResume, isResuming }) => {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)
  const [fileMappings, setFileMappings] = useState<PipelineRemediation['file_mappings']>({})
  const [approvedScripts, setApprovedScripts] = useState<string[]>([])
  const [sqlCompatible, setSqlCompatible] = useState(false)
  const [targetDatabase, setTargetDatabase] = useState('')
  const [targetSchema, setTargetSchema] = useState('')
  const orderedStages = useMemo(() => [...stages].sort((a, b) => Object.keys(stageNames).indexOf(a.stage_id) - Object.keys(stageNames).indexOf(b.stage_id)), [stages])
  const sourceStage = stages.find((stage) => stage.stage_id === 'source_data_ready')
  const providers = (sourceStage?.details?.providers || []) as Array<{ name: string; status: string; details: Record<string, any> }>
  const externalFiles = providers.flatMap((provider) => provider.details?.unmapped_files || []) as Array<{ path: string }>
  const sqlScripts = providers.flatMap((provider) => provider.details?.candidate_scripts || []) as string[]
  const mismatches = (sourceStage?.details?.relation_validation?.mismatches || []) as Array<{ expected: string; actual: Array<{ database: string; schema: string; identifier: string }> }>
  const missingRelations = (sourceStage?.details?.missing_relations || sourceStage?.details?.relation_validation?.missing || []) as Array<string | { expected: string }>
  const configuredTarget = stages.find((stage) => stage.stage_id === 'environment_ready')?.details || {}

  if (!orderedStages.length && !steps.length) {
    return <div className="p-8 text-center text-gray-500 rounded-2xl bg-[#161b22] border border-[#30363d]"><Clock className="w-8 h-8 mx-auto mb-2 text-gray-600 animate-spin" /><p className="text-sm">Pipeline initializing…</p></div>
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-5">
        {orderedStages.map((stage) => {
          const running = stage.status === 'running'
          const Icon = stage.status === 'passed' ? CheckCircle2 : stage.status === 'failed' ? XCircle : stage.status === 'needs_configuration' ? CircleAlert : Clock
          return <div key={stage.stage_id} className={`rounded-xl border p-4 ${running ? 'border-amber-500/40 bg-amber-950/10' : stage.status === 'failed' ? 'border-rose-500/40 bg-rose-950/10' : stage.status === 'needs_configuration' ? 'border-orange-500/40 bg-orange-950/10' : 'border-[#30363d] bg-[#161b22]'}`}>
            <div className="flex items-center gap-2"><Icon className={`h-4 w-4 ${running ? 'text-amber-400 animate-spin' : stage.status === 'passed' ? 'text-emerald-400' : stage.status === 'failed' ? 'text-rose-400' : 'text-gray-400'}`} /><span className="text-sm font-semibold">{stageNames[stage.stage_id] || stage.stage_id}</span></div>
            <span className={`mt-2 inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${statusClass[stage.status] || statusClass.pending}`}>{stage.status.replace('_', ' ')}</span>
            <p className="mt-2 text-xs text-gray-400">{stage.summary}</p>
          </div>
        })}
      </div>

      {mismatches.length > 0 && <section className="rounded-xl border border-orange-500/30 bg-orange-950/10 p-4">
        <h3 className="mb-3 text-sm font-semibold text-orange-200">Source relation location mismatch</h3>
        <div className="space-y-2">{mismatches.map((item) => <div key={item.expected} className="grid gap-2 rounded-lg bg-[#0d1117] p-3 text-xs md:grid-cols-2">
          <div><span className="text-gray-500">Expected relation</span><p className="mt-1 font-mono text-orange-200">{item.expected}</p></div>
          <div><span className="text-gray-500">Discovered relation</span><p className="mt-1 font-mono text-white">{item.actual.map((actual) => `${actual.database}.${actual.schema}.${actual.identifier}`).join(', ')}</p></div>
        </div>)}</div>
        <p className="mt-3 text-xs text-gray-400">Set an explicit target or mapping in run configuration, then resume source preparation.</p>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <input aria-label="Target database" placeholder="Target database or catalog" className="rounded-md border border-[#30363d] bg-[#0d1117] px-2 py-1.5 text-xs text-white" value={targetDatabase} onChange={(event) => setTargetDatabase(event.target.value)} />
          <input aria-label="Target schema" placeholder="Target schema" className="rounded-md border border-[#30363d] bg-[#0d1117] px-2 py-1.5 text-xs text-white" value={targetSchema} onChange={(event) => setTargetSchema(event.target.value)} />
        </div>
        {onResume && <button disabled={isResuming || !targetDatabase.trim() || !targetSchema.trim()} onClick={() => onResume({ file_mappings: {}, approved_sql_scripts: [], target_database: targetDatabase.trim(), target_schema: targetSchema.trim() })} className="mt-3 rounded-lg bg-orange-500 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">{isResuming ? 'Resuming…' : 'Use target settings and resume'}</button>}
      </section>}

      {missingRelations.length > 0 && <section className="rounded-xl border border-rose-500/30 bg-rose-950/10 p-4">
        <h3 className="mb-2 text-sm font-semibold text-rose-200">Missing source relations</h3>
        <ul className="space-y-1 text-xs font-mono text-gray-300">{missingRelations.map((relation) => <li key={typeof relation === 'string' ? relation : relation.expected}>{typeof relation === 'string' ? relation : relation.expected}</li>)}</ul>
      </section>}

      {(externalFiles.length > 0 || sqlScripts.length > 0) && <section className="rounded-xl border border-[#30363d] bg-[#161b22] p-4">
        <h3 className="text-sm font-semibold text-white">Source data remediation</h3>
        {externalFiles.map(({ path }) => <div key={path} className="mt-3 grid gap-2 md:grid-cols-4">
          <div className="flex items-center text-xs font-mono text-gray-300">{path}</div>
          {(['database', 'schema', 'table'] as const).map((field) => <input key={field} aria-label={`${field} for ${path}`} placeholder={field} className="rounded-md border border-[#30363d] bg-[#0d1117] px-2 py-1.5 text-xs text-white" value={fileMappings[path]?.[field] || ''} onChange={(event) => setFileMappings((current) => ({ ...current, [path]: { database: current[path]?.database || '', schema: current[path]?.schema || '', table: current[path]?.table || '', [field]: event.target.value } }))} />)}
        </div>)}
        {sqlScripts.length > 0 && <div className="mt-4 space-y-2">{sqlScripts.map((script) => <label key={script} className="flex items-center gap-2 text-xs text-gray-300"><input type="checkbox" checked={approvedScripts.includes(script)} onChange={(event) => setApprovedScripts((current) => event.target.checked ? [...current, script] : current.filter((item) => item !== script))} />{approvedScripts.includes(script) ? `Run order ${approvedScripts.indexOf(script) + 1}:` : 'Approve setup script'} <span className="font-mono">{script}</span></label>)}
          <p className="text-[11px] text-gray-500">Execution order follows the order you approve scripts. Uncheck and reselect a script to change its position.</p>
          <label className="flex items-center gap-2 text-xs text-gray-400"><input type="checkbox" checked={sqlCompatible} onChange={(event) => setSqlCompatible(event.target.checked)} />Confirm these scripts match the active target adapter</label>
        </div>}
        {onResume && <button disabled={isResuming || externalFiles.some(({ path }) => !fileMappings[path]?.database || !fileMappings[path]?.schema || !fileMappings[path]?.table) || sqlScripts.some((script) => !approvedScripts.includes(script)) || (sqlScripts.length > 0 && !sqlCompatible)} onClick={() => onResume({ file_mappings: fileMappings, approved_sql_scripts: approvedScripts, sql_target_compatibility: sqlCompatible ? String(configuredTarget.type || '') : undefined })} className="mt-4 rounded-lg bg-orange-500 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">{isResuming ? 'Resuming…' : 'Apply preparation choices and resume'}</button>}
      </section>}

      {diagnostics.length > 0 && <section className="space-y-2">{diagnostics.map((diagnostic, index) => <div key={`${diagnostic.category}-${index}`} className="rounded-xl border border-rose-500/30 bg-rose-950/10 p-4"><div className="flex gap-2 text-sm font-semibold text-rose-200"><CircleAlert className="h-4 w-4" />{diagnostic.category}</div><p className="mt-2 text-xs text-gray-300">{diagnostic.message}</p><p className="mt-2 text-xs text-gray-400">Next action: {diagnostic.next_action}</p></div>)}</section>}

      {Object.keys(artifactSnapshots).length > 0 && <details className="rounded-xl border border-[#30363d] bg-[#161b22] p-4"><summary className="cursor-pointer text-sm font-semibold">dbt artifacts</summary><div className="mt-3 space-y-3">{Object.entries(artifactSnapshots).map(([name, artifact]) => <details key={name} className="rounded-lg border border-[#30363d] bg-[#0d1117] p-3"><summary className="cursor-pointer text-xs font-mono text-orange-200">{name}</summary><pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap text-[10px] text-gray-300">{JSON.stringify(artifact, null, 2)}</pre></details>)}</div></details>}

      <div className="space-y-2">{steps.map((step, idx) => {
        const expanded = expandedIndex === idx
        return <div key={`${step.name}-${idx}`} className="rounded-xl border border-[#30363d] bg-[#161b22]">
          <button onClick={() => setExpandedIndex(expanded ? null : idx)} className="flex w-full items-center justify-between p-4 text-left">
            <span className="flex items-center gap-3 text-sm font-semibold"><span>{step.name}</span><span className={`rounded-full px-2 py-0.5 text-[10px] uppercase ${statusClass[step.status] || statusClass.pending}`}>{step.status}</span></span>
            <span className="flex items-center gap-3 text-xs text-gray-400">{step.duration_seconds > 0 ? `${step.duration_seconds.toFixed(2)}s` : ''}{expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</span>
          </button>
          {expanded && step.command?.length > 0 && <div className="border-t border-[#30363d]/50 px-4 pb-4 pt-3"><div className="mb-1 flex items-center gap-1 text-[11px] font-semibold uppercase text-gray-400"><Terminal className="h-3.5 w-3.5" />Command</div><pre className="overflow-x-auto rounded-lg border border-[#30363d] bg-[#0d1117] p-2.5 font-mono text-xs text-orange-300">$ {step.command.join(' ')}</pre></div>}
        </div>
      })}</div>
    </div>
  )
}
