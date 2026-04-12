import { useEffect, useState } from 'react'
import { Activity, Database, RefreshCw, AlertCircle, CheckCircle2, WifiOff } from 'lucide-react'
import { getHealth, getGraphStats, type AgentHealth, type GraphStats } from '../api'

const AGENT_LABELS: Record<string, string> = {
  indexer: 'Indexer',
  graph_query: 'Graph Query',
  code_analyst: 'Code Analyst',
}

export default function Sidebar() {
  const [health, setHealth] = useState<AgentHealth | null>(null)
  const [stats, setStats] = useState<GraphStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [healthError, setHealthError] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    setHealthError(null)

    // Fetch independently — a stats failure shouldn't hide agent health
    const [healthResult, statsResult] = await Promise.allSettled([
      getHealth(),
      getGraphStats(),
    ])

    if (healthResult.status === 'fulfilled') {
      setHealth(healthResult.value)
    } else {
      setHealth(null)
      setHealthError('Gateway offline')
    }

    if (statsResult.status === 'fulfilled') {
      setStats(statsResult.value)
    } else {
      setStats(null)
      // Don't surface a stats error — it's expected before indexing
    }

    setLoading(false)
  }

  useEffect(() => { refresh() }, [])

  return (
    <aside className="w-64 shrink-0 border-r border-slate-800 flex flex-col gap-6 p-4 overflow-y-auto scrollbar-thin">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">System</span>
        <button
          onClick={refresh}
          className="text-slate-500 hover:text-slate-300 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Agent Health */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <Activity size={13} className="text-slate-500" />
          <span className="text-xs text-slate-400 font-medium">Agent Health</span>
        </div>

        {healthError ? (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <WifiOff size={12} className="shrink-0" />
            <span>Gateway not reachable — is Docker running?</span>
          </div>
        ) : health ? (
          <div className="flex flex-col gap-2">
            {Object.entries(health.agents).map(([agent, status]) => (
              <div key={agent} className="flex items-center justify-between">
                <span className="text-xs text-slate-300">{AGENT_LABELS[agent] ?? agent}</span>
                <span className={`flex items-center gap-1 text-xs ${status === 'ok' ? 'text-emerald-400' : 'text-red-400'}`}>
                  {status === 'ok'
                    ? <CheckCircle2 size={11} />
                    : <AlertCircle size={11} />}
                  {status}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {['Indexer', 'Graph Query', 'Code Analyst'].map(name => (
              <div key={name} className="flex items-center justify-between">
                <span className="text-xs text-slate-500">{name}</span>
                <span className="text-xs text-slate-700">
                  {loading ? '…' : '—'}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="border-t border-slate-800" />

      {/* Graph Stats */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <Database size={13} className="text-slate-500" />
          <span className="text-xs text-slate-400 font-medium">Knowledge Graph</span>
        </div>
        {stats && Object.keys(stats).length > 0 ? (
          <div className="flex flex-col gap-2">
            {Object.entries(stats).map(([label, count]) => (
              <div key={label} className="flex items-center justify-between">
                <span className="text-xs text-slate-400">{label}</span>
                <span className="text-xs font-mono text-violet-400">{(count as number).toLocaleString()}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-600 italic">
            {loading ? 'Loading…' : 'No data — index a repo first'}
          </p>
        )}
      </section>

      <div className="mt-auto border-t border-slate-800 pt-4">
        <p className="text-xs text-slate-600 leading-relaxed">
          Powered by Claude + Neo4j + MCP
        </p>
      </div>
    </aside>
  )
}
