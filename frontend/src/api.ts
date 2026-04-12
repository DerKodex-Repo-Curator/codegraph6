const BASE = '/api'

export interface ChatResponse {
  answer: string
  session_id: string
}

export interface IndexResponse {
  job_id: string
  status: string
  message: string
}

export interface IndexStatus {
  job_id: string
  status: string
  progress_pct: number
  processed_files: number
  total_files: number
  error_message?: string
}

export interface AgentHealth {
  status: string
  agents: Record<string, string>
}

export interface GraphStats {
  [label: string]: number
}

export async function postChat(message: string, session_id: string): Promise<ChatResponse> {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id }),
  })
  if (!res.ok) throw new Error(`Chat failed: ${res.status}`)
  return res.json()
}

export function streamChat(
  message: string,
  session_id: string,
  onChunk: (text: string) => void,
  onDone: (sid: string, answer: string) => void,
  onError: (err: string) => void,
): () => void {
  const params = new URLSearchParams({ message, session_id })
  const es = new EventSource(`${BASE}/chat/stream?${params}`)

  es.addEventListener('chunk', (e) => {
    try {
      const d = JSON.parse(e.data)
      onChunk(d.text ?? '')
    } catch {}
  })

  es.addEventListener('done', (e) => {
    try {
      const d = JSON.parse(e.data)
      onDone(d.session_id ?? session_id, d.answer ?? '')
    } catch {}
    es.close()
  })

  es.addEventListener('error', (e: MessageEvent) => {
    try {
      const d = JSON.parse(e.data)
      onError(d.error ?? 'Stream error')
    } catch {
      onError('Stream connection lost')
    }
    es.close()
  })

  return () => es.close()
}

export async function startIndexing(repository_url: string, force = false): Promise<IndexResponse> {
  const res = await fetch(`${BASE}/index`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repository_url, force }),
  })
  if (!res.ok) throw new Error(`Index failed: ${res.status}`)
  return res.json()
}

export async function getIndexStatus(job_id: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/index/status/${job_id}`)
  if (!res.ok) throw new Error(`Status failed: ${res.status}`)
  return res.json()
}

export async function getHealth(): Promise<AgentHealth> {
  const res = await fetch(`${BASE}/agents/health`)
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`)
  return res.json()
}

export async function getGraphStats(): Promise<GraphStats | null> {
  const res = await fetch(`${BASE}/graph/statistics`)
  if (res.status === 404 || res.status === 500) return null   // not indexed yet
  if (!res.ok) throw new Error(`Graph stats failed: ${res.status}`)
  return res.json()
}
