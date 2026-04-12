import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, GitBranch, Loader2, Trash2 } from 'lucide-react'
import ChatMessage, { type Message } from './ChatMessage'
import { streamChat } from '../api'

function friendlyError(raw: string): string {
  if (raw.includes('rate_limit') || raw.includes('429'))
    return "Rate limit reached — the Claude API allows 30k tokens/min on this plan. Wait a minute and try again."
  if (raw.includes('529') || raw.includes('overloaded'))
    return "Claude API is overloaded right now. Try again in a moment."
  if (raw.includes('401') || raw.includes('authentication'))
    return "Authentication error — check that ANTHROPIC_API_KEY is set correctly in your .env file."
  if (raw.includes('AgentUnavailable') || raw.includes('orchestrator'))
    return "The orchestrator agent is unreachable. Check that all Docker containers are healthy (`docker compose ps`)."
  return `Something went wrong: ${raw}`
}

const SAMPLE_QUERIES = [
  'What is the FastAPI class?',
  'How does dependency injection work?',
  'Explain the complete lifecycle of a FastAPI request',
  'What design patterns are used in FastAPI\'s core?',
]

interface Props {
  onShowIndex: () => void
}

export default function ChatPanel({ onShowIndex }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState('')
  const [streaming, setStreaming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const cancelRef = useRef<(() => void) | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function clearChat() {
    if (cancelRef.current) cancelRef.current()
    setMessages([])
    setSessionId('')
    setStreaming(false)
  }

  const sendMessage = useCallback((text: string) => {
    if (!text.trim() || streaming) return

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text.trim(),
    }
    const assistantId = crypto.randomUUID()
    const assistantMsg: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      streaming: true,
    }

    setMessages(prev => [...prev, userMsg, assistantMsg])
    setInput('')
    setStreaming(true)

    // Reset textarea height
    if (textareaRef.current) textareaRef.current.style.height = 'auto'

    let accumulated = ''

    cancelRef.current = streamChat(
      text.trim(),
      sessionId,
      (chunk) => {
        accumulated += chunk
        setMessages(prev =>
          prev.map(m => m.id === assistantId ? { ...m, content: accumulated } : m)
        )
      },
      (sid, _answer) => {
        if (sid) setSessionId(sid)
        setMessages(prev =>
          prev.map(m => m.id === assistantId ? { ...m, streaming: false } : m)
        )
        setStreaming(false)
        cancelRef.current = null
      },
      (err) => {
        setMessages(prev =>
          prev.map(m => m.id === assistantId
            ? { ...m, content: friendlyError(err), streaming: false, isError: true }
            : m)
        )
        setStreaming(false)
        cancelRef.current = null
      },
    )
  }, [sessionId, streaming])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    sendMessage(input)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  function autoResize(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px'
  }

  const isEmpty = messages.length === 0

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Chat header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-300">Chat</span>
          {sessionId && (
            <span className="text-xs text-slate-600 font-mono truncate max-w-[120px]" title={sessionId}>
              #{sessionId.slice(0, 8)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onShowIndex}
            className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
          >
            <GitBranch size={12} />
            Index repo
          </button>
          {messages.length > 0 && (
            <button
              onClick={clearChat}
              className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-red-400 transition-colors"
            >
              <Trash2 size={12} />
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-5 py-4 flex flex-col gap-4">
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center h-full gap-6 text-center">
            <div>
              <h2 className="text-xl font-semibold text-slate-200 mb-2">Ask anything about FastAPI</h2>
              <p className="text-sm text-slate-500 max-w-sm">
                CodeGraph uses a multi-agent system with a Neo4j knowledge graph to answer questions about any codebase.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
              {SAMPLE_QUERIES.map(q => (
                <button
                  key={q}
                  onClick={() => sendMessage(q)}
                  className="text-left text-xs text-slate-400 bg-slate-800/60 hover:bg-slate-800 border border-slate-700/50 rounded-lg px-3 py-2.5 transition-colors leading-relaxed"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map(msg => (
              <ChatMessage key={msg.id} message={msg} />
            ))}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="shrink-0 border-t border-slate-800 p-4">
        <form onSubmit={handleSubmit} className="flex gap-2 items-end">
          <div className="flex-1 bg-slate-900 border border-slate-700 focus-within:border-violet-500 rounded-xl transition-colors">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={autoResize}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question about the FastAPI codebase… (Enter to send, Shift+Enter for newline)"
              rows={1}
              className="w-full bg-transparent px-4 py-3 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none resize-none leading-relaxed"
              style={{ maxHeight: '160px' }}
            />
          </div>
          <button
            type="submit"
            disabled={!input.trim() || streaming}
            className="w-10 h-10 rounded-xl bg-violet-600 hover:bg-violet-500 disabled:bg-slate-700 disabled:text-slate-500 text-white flex items-center justify-center transition-colors shrink-0"
          >
            {streaming
              ? <Loader2 size={15} className="animate-spin" />
              : <Send size={15} />}
          </button>
        </form>
        <p className="text-xs text-slate-700 mt-1.5 text-right">
          Shift+Enter for newline
        </p>
      </div>
    </div>
  )
}
