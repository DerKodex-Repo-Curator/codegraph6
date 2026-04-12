import { useState, useEffect, useRef } from 'react'
import { GitBranch, Loader2, CheckCircle2, AlertCircle, RefreshCw } from 'lucide-react'
import { startIndexing, getIndexStatus } from '../api'

interface Props {
  onIndexed: () => void
}

// Normalise the two possible response shapes from the status endpoint:
//   Real:  { status, progress_pct, processed_files, total_files, error_message }
//   Chat:  { answer, session_id }
interface NormalisedStatus {
  phase: 'running' | 'completed' | 'failed'
  label: string
  progress_pct: number
  processed_files: number
  total_files: number
}

function normalise(raw: Record<string, unknown>): NormalisedStatus {
  // Real structured response
  if (typeof raw.status === 'string') {
    const phase =
      raw.status === 'completed' ? 'completed'
      : raw.status === 'failed' ? 'failed'
      : 'running'
    return {
      phase,
      label: raw.status as string,
      progress_pct: (raw.progress_pct as number) ?? 0,
      processed_files: (raw.processed_files as number) ?? 0,
      total_files: (raw.total_files as number) ?? 0,
    }
  }

  // Chat-shaped response — infer completion from the answer text
  if (typeof raw.answer === 'string') {
    const answer = raw.answer.toLowerCase()
    const done = /complet|finish|done|success/.test(answer)
    const failed = /fail|error/.test(answer)
    return {
      phase: done ? 'completed' : failed ? 'failed' : 'running',
      label: raw.answer as string,
      progress_pct: 0,
      processed_files: 0,
      total_files: 0,
    }
  }

  // Unknown shape — treat as in-progress
  return { phase: 'running', label: 'Indexing in progress…', progress_pct: 0, processed_files: 0, total_files: 0 }
}

export default function IndexPanel({ onIndexed }: Props) {
  const [url, setUrl] = useState('https://github.com/tiangolo/fastapi')
  const [force, setForce] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [normStatus, setNormStatus] = useState<NormalisedStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  useEffect(() => () => stopPolling(), [])

  async function poll(id: string) {
    try {
      const raw = await getIndexStatus(id)
      if (!raw) return
      const ns = normalise(raw as Record<string, unknown>)
      setNormStatus(ns)
      if (ns.phase === 'completed') {
        stopPolling()
        onIndexed()
      } else if (ns.phase === 'failed') {
        stopPolling()
        setError(ns.label)
      }
    } catch {
      // silently retry on network hiccup
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setNormStatus(null)
    setLoading(true)
    stopPolling()

    try {
      const res = await startIndexing(url, force)

      // If the backend returned an error body (500) it will have thrown above.
      // job_id may be "unknown" when the backend routes through the LLM layer.
      const id = res.job_id ?? 'unknown'
      setJobId(id)

      // Show optimistic "pending" state immediately
      setNormStatus({ phase: 'running', label: 'pending', progress_pct: 0, processed_files: 0, total_files: 0 })

      pollRef.current = setInterval(() => poll(id), 3000)
      await poll(id)
    } catch (e: any) {
      const msg: string = e.message ?? 'Failed to start indexing'
      // Surface rate-limit errors helpfully
      if (msg.includes('rate_limit') || msg.includes('429')) {
        setError('Claude API rate limit hit — wait a minute and try again.')
      } else {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  const isRunning = normStatus?.phase === 'running'
  const isDone = normStatus?.phase === 'completed'

  // Display label: for short status strings show a canned message, for long
  // chat-style answers show the raw text.
  const displayLabel = (() => {
    if (!normStatus) return ''
    if (isDone) return 'Indexing complete'
    if (normStatus.phase === 'failed') return 'Indexing failed'
    const l = normStatus.label
    if (l.length < 30) {
      // Short structured status like "pending", "running", "indexing"
      return `Indexing… (${l})`
    }
    // LLM-synthesised answer — show it as-is
    return l
  })()

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="text-lg font-semibold text-slate-100 mb-1 flex items-center gap-2">
          <GitBranch size={18} className="text-violet-400" />
          Index a Repository
        </h2>
        <p className="text-sm text-slate-400">
          Point CodeGraph at a GitHub repo to build a knowledge graph. Then ask anything about the code.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex gap-2">
          <input
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            required
            className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-violet-500 transition-colors"
          />
          <button
            type="submit"
            disabled={loading || isRunning}
            className="px-4 py-2 bg-violet-600 hover:bg-violet-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm rounded-lg transition-colors flex items-center gap-2 shrink-0"
          >
            {loading || isRunning
              ? <><Loader2 size={14} className="animate-spin" /> Indexing…</>
              : isDone
              ? <><RefreshCw size={14} /> Re-index</>
              : 'Index'}
          </button>
        </div>

        <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={force}
            onChange={e => setForce(e.target.checked)}
            className="rounded border-slate-600 bg-slate-800 accent-violet-500"
          />
          Force re-index (ignore cached commit SHA)
        </label>
      </form>

      {/* Progress */}
      {normStatus && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 flex flex-col gap-3">
          <div className="flex items-start justify-between gap-3 text-sm">
            <span className="flex items-start gap-2 min-w-0">
              {isDone
                ? <CheckCircle2 size={14} className="text-emerald-400 mt-0.5 shrink-0" />
                : normStatus.phase === 'failed'
                ? <AlertCircle size={14} className="text-red-400 mt-0.5 shrink-0" />
                : <Loader2 size={14} className="animate-spin text-violet-400 mt-0.5 shrink-0" />}
              <span className={`leading-snug ${isDone ? 'text-emerald-400' : normStatus.phase === 'failed' ? 'text-red-400' : 'text-slate-300'}`}>
                {displayLabel}
              </span>
            </span>
            {normStatus.progress_pct > 0 && (
              <span className="text-xs text-slate-500 font-mono shrink-0">
                {normStatus.processed_files}/{normStatus.total_files} files
              </span>
            )}
          </div>

          {normStatus.progress_pct > 0 && (
            <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
              <div
                className="h-full bg-violet-500 rounded-full transition-all duration-300"
                style={{ width: `${Math.min(normStatus.progress_pct, 100)}%` }}
              />
            </div>
          )}

          {/* When job_id is unknown, polling can't give structured progress */}
          {jobId === 'unknown' && isRunning && (
            <p className="text-xs text-slate-600">
              Indexing runs in the background — this takes 2–5 minutes. You can close this panel and come back.
            </p>
          )}
        </div>
      )}

      {error && (
        <div className="text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2 flex gap-2 items-start">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          {error}
        </div>
      )}
    </div>
  )
}
